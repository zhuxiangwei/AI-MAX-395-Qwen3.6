#!/usr/bin/env python3
"""bench_358_full.py — 35B MoE F16 KV full context benchmark.

Tests 358 (35B-A3B Q8 MoE) at p128/p4K/p32K/p64K/p128K/p256K.
Restarts llama-server between each test point.
No max_tokens limit — model generates freely.
F16 KV cache only.
Results written to CSV.

Usage (on inference machine):
    python3 -u bench_358_full.py
"""

import subprocess
import time
import json
import csv
import os
import sys
import urllib.request
import urllib.error
import signal

# ── Configuration ──────────────────────────────────────────────
_BASE_DIR = os.environ.get("LLM_BASE_DIR", "/home/user")
LLAMA_SERVER = os.path.join(_BASE_DIR, "llama/llama.cpp/build/bin/llama-server")
MODEL_PATH = os.path.join(_BASE_DIR, "model/Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_bench_data.txt")
CSV_FILE = os.path.join(_BASE_DIR, "test/bench_358_full.csv")
API_BASE = "http://127.0.0.1:12345"
API_KEY = os.environ.get("LLM_API_KEY", "")

CTX = 262144
BATCH = 4096
UBATCH = 256
THREADS = 8
REASONING_BUDGET = 8192

CHARS_PER_TOKEN = 3.6  # Qwen3.6 tokenizer ratio

TEST_POINTS = [
    ("p128",   128),
    ("p4K",    4096),
    ("p32K",   32768),
    ("p64K",   65536),
    ("p128K",  131072),
    ("p256K",  242000),
]

SERVER_READY_TIMEOUT = 180  # seconds to wait for server startup
REQUEST_TIMEOUT = 3600      # max seconds per request (256K prefill ~17min)

# ── Server Management ──────────────────────────────────────────
server_pid = None

def start_server():
    """Start llama-server with F16 KV cache, return PID."""
    global server_pid
    stop_server()  # ensure clean state

    cmd = [
        LLAMA_SERVER,
        "--model", MODEL_PATH,
        "--n-gpu-layers", "99",
        "--ctx-size", str(CTX),
        "--batch-size", str(BATCH),
        "--ubatch-size", str(UBATCH),
        "--threads", str(THREADS),
        "--flash-attn", "on",
        "--parallel", "1",
        "--spec-type", "draft-mtp",
        "--spec-draft-n-max", "3",
        "--mlock",
        "--numa", "distribute",
        "--reasoning-budget", str(REASONING_BUDGET),
        "--host", "127.0.0.1",
        "--port", "12345",
        "--api-key", API_KEY,
        "--alias", "358",
        "--timeout", "3600",
    ]

    log_file = open(os.path.join(_BASE_DIR, "test/server_bench.log"), "w")
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    server_pid = proc.pid
    print(f"  [SERVER] Started PID={server_pid}, waiting for ready...")

    # Wait for server to be ready
    t0 = time.time()
    while time.time() - t0 < SERVER_READY_TIMEOUT:
        try:
            req = urllib.request.Request(f"{API_BASE}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    elapsed = time.time() - t0
                    print(f"  [SERVER] Ready in {elapsed:.1f}s")
                    return True
        except Exception:
            pass
        time.sleep(2)

    print(f"  [SERVER] FAILED to start within {SERVER_READY_TIMEOUT}s")
    stop_server()
    return False


def stop_server():
    """Kill llama-server process."""
    global server_pid
    try:
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, timeout=10)
    except Exception:
        pass
    # Also kill by PID if we have it
    if server_pid:
        try:
            os.kill(server_pid, signal.SIGTERM)
        except Exception:
            pass
    server_pid = None
    time.sleep(2)  # wait for port to free
    # Verify port is free
    try:
        subprocess.run(["fuser", "12345/tcp"], capture_output=True, timeout=5)
    except Exception:
        pass
    print(f"  [SERVER] Stopped")


# ── Benchmark ──────────────────────────────────────────────────
def load_prompt_data():
    """Load ffmpeg_filters_text.txt."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return f.read()


def make_prompt(text, target_tokens):
    """Truncate text to approximately target_tokens characters, add question."""
    target_chars = int(target_tokens * CHARS_PER_TOKEN)
    truncated = text[:target_chars]
    actual_tokens_est = len(truncated) / CHARS_PER_TOKEN

    prompt = (
        f"{truncated}\n\n"
        f"---\n"
        f"Summarize the above content in 2-3 sentences."
    )
    return prompt, int(actual_tokens_est)


def run_test(prompt, prompt_tokens_est):
    """Send chat completion request, parse SSE stream, return metrics."""
    payload = json.dumps({
        "model": "358",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    t0 = time.time()
    first_token_time = None
    content_tokens = 0
    reasoning_tokens = 0
    prompt_tokens_actual = 0
    completion_tokens_actual = 0

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            buf = b""
            while True:
                chunk = resp.read(1)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").strip()

                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    # Track first token (could be reasoning or content)
                    if first_token_time is None:
                        if delta.get("reasoning_content") or delta.get("content"):
                            first_token_time = time.time()

                    # Count tokens by tracking non-empty deltas
                    if delta.get("reasoning_content"):
                        reasoning_tokens += 1
                    if delta.get("content"):
                        content_tokens += 1

                    # Check usage in the final chunk
                    usage = data.get("usage")
                    if usage:
                        prompt_tokens_actual = usage.get("prompt_tokens", 0)
                        completion_tokens_actual = usage.get("completion_tokens", 0)

    except urllib.error.URLError as e:
        elapsed = time.time() - t0
        return {"error": f"URL Error: {e}", "elapsed_s": elapsed}
    except Exception as e:
        elapsed = time.time() - t0
        return {"error": f"Exception: {e}", "elapsed_s": elapsed}

    elapsed = time.time() - t0
    ttft = (first_token_time - t0) if first_token_time else None

    # Calculate speeds using actual usage data if available
    total_completion = completion_tokens_actual if completion_tokens_actual else (reasoning_tokens + content_tokens)

    result = {
        "elapsed_s": round(elapsed, 2),
        "prompt_tokens": prompt_tokens_actual or prompt_tokens_est,
        "completion_tokens": completion_tokens_actual or total_completion,
        "ttft_s": round(ttft, 3) if ttft else None,
    }

    # Prefill speed
    if ttft and prompt_tokens_actual:
        result["prefill_tps"] = round(prompt_tokens_actual / ttft, 1)
    elif ttft and prompt_tokens_est:
        result["prefill_tps"] = round(prompt_tokens_est / ttft, 1)

    # Generation speed (from first token to end)
    if ttft and total_completion > 0:
        gen_time = elapsed - ttft
        if gen_time > 0:
            result["gen_tps"] = round(total_completion / gen_time, 1)

    return result


# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 64)
    print("  35B MoE F16 KV — Full Context Benchmark")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    # Load prompt data
    print("\n[INIT] Loading prompt data...")
    text = load_prompt_data()
    print(f"  Data: {len(text)} chars, ~{len(text)/CHARS_PER_TOKEN:.0f} tokens estimated")

    results = []

    # Stop any existing server first
    print("\n[INIT] Stopping any existing llama-server...")
    subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, timeout=10)
    time.sleep(3)

    # CSV header
    csv_fields = ["test", "prompt_tokens", "completion_tokens", "ttft_s",
                  "prefill_tps", "gen_tps", "elapsed_s", "error"]

    for i, (name, target_tok) in enumerate(TEST_POINTS):
        print(f"\n{'─' * 64}")
        print(f"  [{i+1}/{len(TEST_POINTS)}] {name} (target ~{target_tok} tokens)")
        print(f"{'─' * 64}")

        # Step 1: Start server
        if not start_server():
            print(f"  [FAIL] Could not start server, skipping {name}")
            results.append({"test": name, "error": "server start failed"})
            continue

        # Step 2: Prepare prompt
        prompt, est_tokens = make_prompt(text, target_tok)
        print(f"  Prompt: {len(prompt)} chars, ~{est_tokens} tokens estimated")

        # Step 3: Run test
        print(f"  Running test (no max_tokens limit, streaming)...")
        result = run_test(prompt, est_tokens)
        result["test"] = name
        results.append(result)

        if "error" in result:
            print(f"  [FAIL] {result['error']}")
        else:
            pt = result.get("prompt_tokens", "?")
            ct = result.get("completion_tokens", "?")
            ttft = result.get("ttft_s", "?")
            pf = result.get("prefill_tps", "?")
            gf = result.get("gen_tps", "?")
            print(f"  [OK] prompt={pt}, completion={ct}, ttft={ttft}s")
            print(f"       prefill={pf} t/s, gen={gf} t/s, total={result['elapsed_s']}s")

        # Step 4: Stop server
        stop_server()

        # Write CSV after each test (incremental save)
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"  CSV saved to {CSV_FILE}")

    # ── Final Summary ──
    print(f"\n{'=' * 64}")
    print("  Benchmark Complete")
    print(f"{'=' * 64}")
    print(f"  {'Test':<8} {'Prompt':>8} {'Compl':>8} {'TTFT':>10} {'Prefill':>10} {'Gen':>10} {'Total':>8}")
    print(f"  {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
    for r in results:
        if "error" in r and r.get("test"):
            print(f"  {r['test']:<8} {'ERROR':>8} {r.get('error', '')[:40]}")
        else:
            pt = r.get("prompt_tokens", "?")
            ct = r.get("completion_tokens", "?")
            ttft = f"{r.get('ttft_s', '?')}s" if r.get('ttft_s') else "?"
            pf = f"{r.get('prefill_tps', '?')} t/s" if r.get('prefill_tps') else "?"
            gf = f"{r.get('gen_tps', '?')} t/s" if r.get('gen_tps') else "?"
            el = f"{r.get('elapsed_s', '?')}s"
            print(f"  {r.get('test','?'):<8} {str(pt):>8} {str(ct):>8} {ttft:>10} {pf:>10} {gf:>10} {el:>8}")

    print(f"\n  Results: {CSV_FILE}")
    print(f"  Server log: {os.path.join(_BASE_DIR, 'test/server_bench.log')}")


if __name__ == "__main__":
    # Validate required env vars
    if not API_KEY:
        print("ERROR: LLM_API_KEY environment variable not set. Aborting.")
        sys.exit(1)
    main()
