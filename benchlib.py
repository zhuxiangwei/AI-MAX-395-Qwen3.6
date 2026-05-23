#!/usr/bin/env python3
"""benchlib.py — Shared benchmark library for Strix Halo LLM testing.

Provides:
- Server management (start/stop llama-server, with service disable/enable)
- Prompt generation (truncate ffmpeg data to target tokens)
- SSE stream parsing (prefill/gen/TTFT metrics + MTP draft stats)
- CSV output with incremental save
- Standard test workflow enforcement

Usage (imported by 01-08 test scripts):
    import benchlib
"""

import subprocess
import time
import json
import csv
import os
import sys
import signal
import urllib.request
import urllib.error

# ── Constants ──────────────────────────────────────────────────
CHARS_PER_TOKEN = 3.6  # Qwen3.6 tokenizer ratio
DEFAULT_CTX = 262144
DEFAULT_BATCH = 4096
DEFAULT_THREADS = 8
DEFAULT_REASONING_BUDGET = 8192
DEFAULT_SERVER_PORT = 12345
DEFAULT_SERVER_READY_TIMEOUT = 180
DEFAULT_REQUEST_TIMEOUT = 7200  # 2 hours for 256K prefill


# ── Server Management ──────────────────────────────────────────
def acquire_lock(lock_name="bench"):
    """Acquire a PID lock file to prevent duplicate bench script instances.
    
    Creates /tmp/bench_<lock_name>.lock with current PID.
    If lock exists and process is alive, abort with error.
    If lock exists but process is dead, steal the lock.
    """
    lock_file = f"/tmp/bench_{lock_name}.lock"
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                old_pid = int(f.read().strip())
            # Check if process is still alive
            os.kill(old_pid, 0)  # Raises OSError if dead
            print(f"  [LOCK] ERROR: Another bench instance is running (PID {old_pid})")
            print(f"  [LOCK] Lock file: {lock_file}")
            print(f"  [LOCK] If stale, run: rm {lock_file}")
            sys.exit(1)
        except (OSError, ProcessLookupError, ValueError):
            # Process is dead, steal the lock
            print(f"  [LOCK] Stale lock found (PID {old_pid} dead), stealing...")
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))
    print(f"  [LOCK] Acquired lock: {lock_file} (PID {os.getpid()})")


def release_lock(lock_name="bench"):
    """Release the PID lock file."""
    lock_file = f"/tmp/bench_{lock_name}.lock"
    try:
        os.remove(lock_file)
    except OSError:
        pass


def disable_router_service():
    """Stop and disable llm-router service to prevent auto-restart during benchmarks."""
    print("  [SERVICE] Stopping and disabling llm-router...")
    try:
        subprocess.run(["systemctl", "--user", "stop", "llm-router.service"],
                       capture_output=True, timeout=30)
        subprocess.run(["systemctl", "--user", "disable", "llm-router.service"],
                       capture_output=True, timeout=30)
    except Exception as e:
        print(f"  [SERVICE] Warning: {e}")
    time.sleep(2)


def enable_router_service():
    """Re-enable and start llm-router service after benchmarks."""
    print("  [SERVICE] Re-enabling llm-router...")
    try:
        subprocess.run(["systemctl", "--user", "enable", "llm-router.service"],
                       capture_output=True, timeout=30)
        subprocess.run(["systemctl", "--user", "start", "llm-router.service"],
                       capture_output=True, timeout=30)
    except Exception as e:
        print(f"  [SERVICE] Warning: {e}")


def kill_all_llama():
    """Kill all llama-server processes, ensure clean state."""
    print("  [CLEANUP] Killing all llama-server processes...")
    try:
        subprocess.run(["pkill", "-9", "-f", "llama-server"],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    time.sleep(3)
    # Verify port is free
    for _ in range(10):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/health")
            urllib.request.urlopen(req, timeout=2)
            time.sleep(2)
        except Exception:
            break
    print("  [CLEANUP] Done")


class LlamaServer:
    """Context manager for llama-server process lifecycle."""

    def __init__(self, model_path, alias, base_dir, api_key="",
                 ubatch=256, cache_type_k="f16", cache_type_v="f16",
                 ctx=DEFAULT_CTX, batch=DEFAULT_BATCH, threads=DEFAULT_THREADS,
                 port=DEFAULT_SERVER_PORT,
                 ready_timeout=DEFAULT_SERVER_READY_TIMEOUT):
        self.model_path = model_path
        self.alias = alias
        self.base_dir = base_dir
        self.api_key = api_key
        self.ubatch = ubatch
        self.cache_type_k = cache_type_k
        self.cache_type_v = cache_type_v
        self.ctx = ctx
        self.batch = batch
        self.threads = threads
        self.port = port
        self.ready_timeout = ready_timeout
        self.pid = None
        self.log_file = None

    def start(self):
        """Start llama-server, wait until ready. Returns True on success."""
        self.stop()  # ensure clean state

        cmd = [
            os.path.join(self.base_dir, "llama/llama.cpp/build/bin/llama-server"),
            "--model", self.model_path,
            "--n-gpu-layers", "99",
            "--ctx-size", str(self.ctx),
            "--batch-size", str(self.batch),
            "--ubatch-size", str(self.ubatch),
            "--threads", str(self.threads),
            "--flash-attn", "on",
            "--parallel", "1",
            "--spec-type", "draft-mtp",
            "--spec-draft-n-max", "3",
            "--mlock",
            "--numa", "distribute",
            "--reasoning-budget", str(DEFAULT_REASONING_BUDGET),
            "--cache-type-k", self.cache_type_k,
            "--cache-type-v", self.cache_type_v,
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--api-key", self.api_key,
            "--alias", self.alias,
            "--timeout", "3600",
        ]

        log_path = os.path.join(self.base_dir, "test/server_bench.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self.log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=self.log_file, stderr=subprocess.STDOUT)
        self.pid = proc.pid
        kv_desc = f"KV={self.cache_type_k}/{self.cache_type_v}" if self.cache_type_k != "f16" else "F16 KV"
        print(f"  [SERVER] Started PID={self.pid}, UB={self.ubatch}, {kv_desc}, waiting...")

        t0 = time.time()
        while time.time() - t0 < self.ready_timeout:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{self.port}/health")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    if data.get("status") == "ok":
                        print(f"  [SERVER] Ready in {time.time()-t0:.1f}s")
                        return True
            except Exception:
                pass
            time.sleep(2)

        print(f"  [SERVER] FAILED to start within {self.ready_timeout}s")
        self.stop()
        return False

    def stop(self):
        """Kill llama-server process."""
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception:
                pass
        try:
            subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, timeout=10)
        except Exception:
            pass
        self.pid = None
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None
        time.sleep(2)
        print(f"  [SERVER] Stopped")

    def read_log(self):
        """Read server log file, return content as string."""
        log_path = os.path.join(self.base_dir, "test/server_bench.log")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""


# ── MTP Detection ──────────────────────────────────────────────
def extract_mtp_stats(log_text):
    """Extract MTP draft statistics from llama-server log.

    Looks for lines like:
      "draft spec decode: n_draft = 100, n_accept = 86, acceptance rate = 86.0%"
      "speculative decoding: n_draft = ..., n_accept = ..., n_draft_total = ..."

    Returns dict with keys: n_draft, n_accept, acceptance_rate (or empty dict)
    """
    stats = {}
    for line in log_text.splitlines():
        low = line.lower()
        # b9210 format
        if "accept" in low and "rate" in low:
            # Try to parse acceptance rate
            try:
                if "acceptance rate" in low:
                    # "acceptance rate = 86.0%"
                    parts = line.split("acceptance rate")
                    if len(parts) > 1:
                        rate_str = parts[1].strip().lstrip("=").strip().rstrip("%")
                        stats["acceptance_rate"] = float(rate_str)
                if "n_accept" in low or "n draft" in low or "n_draft" in low:
                    # Parse n_draft and n_accept
                    import re
                    m = re.search(r'n[_ ]draft[_ ]?(?:total)?\s*[=:]\s*(\d+)', line, re.I)
                    if m:
                        stats["n_draft"] = int(m.group(1))
                    m = re.search(r'n[_ ]accept\s*[=:]\s*(\d+)', line, re.I)
                    if m:
                        stats["n_accept"] = int(m.group(1))
            except (ValueError, IndexError):
                pass
    return stats


# ── Prompt Generation ──────────────────────────────────────────
def load_prompt_data(script_path):
    """Load test_bench_data.txt from same directory as the script."""
    data_file = os.path.join(os.path.dirname(os.path.abspath(script_path)), "test_bench_data.txt")
    with open(data_file, "r", encoding="utf-8") as f:
        return f.read()


def make_prompt(text, target_tokens):
    """Truncate text to approximately target_tokens, add summarization question."""
    target_chars = int(target_tokens * CHARS_PER_TOKEN)
    truncated = text[:target_chars]
    actual_tokens_est = len(truncated) / CHARS_PER_TOKEN

    prompt = (
        f"{truncated}\n\n"
        f"---\n"
        f"Summarize the above content in 2-3 sentences."
    )
    return prompt, int(actual_tokens_est)


# ── SSE Benchmark ──────────────────────────────────────────────
def run_test(server, prompt, prompt_tokens_est, alias,
             request_timeout=DEFAULT_REQUEST_TIMEOUT):
    """Send chat completion request, parse SSE stream, return metrics dict.

    Key requirements enforced:
    - No max_tokens limit (model generates freely)
    - Streaming output
    - Thinking enabled with budget
    """
    api_base = f"http://127.0.0.1:{server.port}"
    payload = json.dumps({
        "model": alias,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {server.api_key}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        f"{api_base}/chat/completions",
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
        with urllib.request.urlopen(req, timeout=request_timeout) as resp:
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

                    if first_token_time is None:
                        if delta.get("reasoning_content") or delta.get("content"):
                            first_token_time = time.time()

                    if delta.get("reasoning_content"):
                        reasoning_tokens += 1
                    if delta.get("content"):
                        content_tokens += 1

                    usage = data.get("usage")
                    if usage:
                        prompt_tokens_actual = usage.get("prompt_tokens", 0)
                        completion_tokens_actual = usage.get("completion_tokens", 0)

    except urllib.error.URLError as e:
        elapsed = time.time() - t0
        return {"error": f"URL Error: {e}", "elapsed_s": round(elapsed, 2)}
    except Exception as e:
        elapsed = time.time() - t0
        return {"error": f"Exception: {e}", "elapsed_s": round(elapsed, 2)}

    elapsed = time.time() - t0
    ttft = (first_token_time - t0) if first_token_time else None

    total_completion = completion_tokens_actual if completion_tokens_actual else (reasoning_tokens + content_tokens)

    result = {
        "elapsed_s": round(elapsed, 2),
        "prompt_tokens": prompt_tokens_actual or prompt_tokens_est,
        "completion_tokens": completion_tokens_actual or total_completion,
        "ttft_s": round(ttft, 3) if ttft else None,
    }

    if ttft and prompt_tokens_actual:
        result["prefill_tps"] = round(prompt_tokens_actual / ttft, 1)
    elif ttft and prompt_tokens_est:
        result["prefill_tps"] = round(prompt_tokens_est / ttft, 1)

    if ttft and total_completion > 0:
        gen_time = elapsed - ttft
        if gen_time > 0:
            result["gen_tps"] = round(total_completion / gen_time, 1)

    # Extract MTP stats from server log
    log_text = server.read_log()
    mtp = extract_mtp_stats(log_text)
    if mtp:
        result["mtp_draft"] = mtp.get("n_draft")
        result["mtp_accept"] = mtp.get("n_accept")
        result["mtp_rate"] = mtp.get("acceptance_rate")

    return result


# ── CSV Output ─────────────────────────────────────────────────
CSV_FIELDS = ["test", "prompt_tokens", "completion_tokens", "ttft_s",
              "prefill_tps", "gen_tps", "mtp_rate", "mtp_draft", "mtp_accept",
              "elapsed_s", "error"]


def save_csv(results, csv_path):
    """Write results to CSV file."""
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)


def print_summary(results):
    """Print benchmark summary table."""
    print(f"\n{'=' * 80}")
    print("  Benchmark Complete")
    print(f"{'=' * 80}")
    print(f"  {'Test':<8} {'Prompt':>8} {'Compl':>8} {'TTFT':>10} "
          f"{'Prefill':>10} {'Gen':>10} {'MTP':>6} {'Total':>8}")
    print(f"  {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*10} {'─'*10} {'─'*6} {'─'*8}")
    for r in results:
        if "error" in r and r.get("test"):
            print(f"  {r['test']:<8} {'ERROR':>8} {r.get('error', '')[:40]}")
        else:
            pt = r.get("prompt_tokens", "?")
            ct = r.get("completion_tokens", "?")
            ttft = f"{r.get('ttft_s', '?')}s" if r.get('ttft_s') else "?"
            pf = f"{r.get('prefill_tps', '?')} t/s" if r.get('prefill_tps') else "?"
            gf = f"{r.get('gen_tps', '?')} t/s" if r.get('gen_tps') else "?"
            mtp = f"{r.get('mtp_rate', '?')}%" if r.get('mtp_rate') else "—"
            el = f"{r.get('elapsed_s', '?')}s"
            print(f"  {r.get('test','?'):<8} {str(pt):>8} {str(ct):>8} {ttft:>10} "
                  f"{pf:>10} {gf:>10} {mtp:>6} {el:>8}")
