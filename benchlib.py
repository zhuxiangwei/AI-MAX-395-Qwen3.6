#!/usr/bin/env python3
"""benchlib.py — Minimal benchmark library for Strix Halo LLM testing.

Design principle: SIMPLE > CLEVER. No over-abstraction.
Test scripts are themselves test code — don't make them need their own tests.

Provides:
- kill_all_llama: pkill -9 + verify dead
- wait_clean: kill + verify + wait memory — LOOPS FOREVER until clean
- LlamaServer: start/stop (minimal wrapper around subprocess)
- Prompt generation, SSE parsing, CSV output
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
CHARS_PER_TOKEN = 3.6
DEFAULT_CTX = 262144
DEFAULT_BATCH = 4096
DEFAULT_THREADS = 8
DEFAULT_REASONING_BUDGET = 8192
DEFAULT_SERVER_PORT = 12345
DEFAULT_SERVER_READY_TIMEOUT = 180
DEFAULT_REQUEST_TIMEOUT = 7200


# ── Kill + Clean + Wait ────────────────────────────────────────

def _get_mem_available_gb():
    """Read MemAvailable from /proc/meminfo, return GB."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return -1


def _get_mem_total_gb():
    """Read MemTotal from /proc/meminfo, return GB."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return 32  # fallback


def _pgrep_llama():
    """Return list of llama-server PIDs, empty if none."""
    try:
        r = subprocess.run(["pgrep", "-f", "llama-server"],
                           capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            return [int(x) for x in r.stdout.strip().splitlines()]
    except Exception:
        pass
    return []


def _port_in_use(port=DEFAULT_SERVER_PORT):
    """Check if port has a live llama-server."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        urllib.request.urlopen(req, timeout=2)
        return True
    except Exception:
        return False


def kill_all_llama():
    """pkill -9 all llama-server, verify dead. Returns True if clean."""
    print("  [KILL] Killing all llama-server...")
    for attempt in range(5):
        try:
            subprocess.run(["pkill", "-9", "-f", "llama-server"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        time.sleep(2)
        pids = _pgrep_llama()
        if not pids:
            break
        print(f"  [KILL] Attempt {attempt+1}: still alive PIDs={pids}")
    pids = _pgrep_llama()
    if pids:
        print(f"  [KILL] WARNING: PIDs still alive: {pids}")
        return False
    # Wait for port to be freed
    for _ in range(10):
        if not _port_in_use():
            break
        time.sleep(2)
    print("  [KILL] All llama-server dead, port free")
    return True


def wait_clean(target_gb=None):
    """Kill + clean + wait. LOOPS FOREVER until conditions met.
    
    - Repeatedly kill residual llama-server processes
    - Wait for available memory to reach target (default 75% of total)
    - Does NOT return until clean — this is intentional
    """
    if target_gb is None:
        target_gb = _get_mem_total_gb() * 0.75
    
    round_num = 0
    while True:
        round_num += 1
        # 1. Kill any residual processes
        kill_all_llama()
        
        # 2. Check memory
        avail = _get_mem_available_gb()
        port_ok = not _port_in_use()
        pids = _pgrep_llama()
        
        print(f"  [WAIT] Round {round_num}: avail={avail:.1f}GB / target={target_gb:.1f}GB, "
              f"port_free={port_ok}, pids={pids}")
        
        if avail >= target_gb and port_ok and not pids:
            print(f"  [WAIT] Clean! avail={avail:.1f}GB >= {target_gb:.1f}GB")
            return True
        
        # Not clean yet — wait and loop again
        print(f"  [WAIT] Not clean yet, waiting 10s and retrying...")
        time.sleep(10)


# ── Lock ───────────────────────────────────────────────────────

def acquire_lock(lock_name="bench"):
    """PID lock to prevent duplicate instances."""
    lock_file = f"/tmp/bench_{lock_name}.lock"
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"  [LOCK] ERROR: Another bench running (PID {old_pid})")
            print(f"  [LOCK] If stale: rm {lock_file}")
            sys.exit(1)
        except (OSError, ProcessLookupError, ValueError):
            print(f"  [LOCK] Stale lock (PID {old_pid} dead), stealing...")
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))
    print(f"  [LOCK] Acquired: {lock_file}")


def release_lock(lock_name="bench"):
    lock_file = f"/tmp/bench_{lock_name}.lock"
    try:
        os.remove(lock_file)
    except OSError:
        pass


# ── Router Service ─────────────────────────────────────────────

def disable_router_service():
    """Stop and disable llm-router service."""
    print("  [SERVICE] Stopping and disabling llm-router...")
    try:
        subprocess.run(["systemctl", "--user", "stop", "llm-router.service"],
                       capture_output=True, timeout=30)
        subprocess.run(["systemctl", "--user", "disable", "llm-router.service"],
                       capture_output=True, timeout=30)
    except Exception as e:
        print(f"  [SERVICE] Warning: {e}")
    time.sleep(2)


# NOTE: No enable_router_service() — per user rule, re-enable manually after all tests


# ── LlamaServer ────────────────────────────────────────────────

class LlamaServer:
    """Minimal llama-server wrapper. start() calls wait_clean() first."""

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
        """Start llama-server. Calls wait_clean() first. Returns True on success."""
        # Ensure absolutely clean before starting
        wait_clean()

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
        print(f"  [SERVER] Started PID={self.pid}, UB={self.ubatch}, {kv_desc}")

        # Wait for ready
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
        """Kill llama-server, verify dead, wait clean."""
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception:
                pass
            time.sleep(1)
        # Force kill ALL llama-server (not just our PID)
        kill_all_llama()
        self.pid = None
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None
        # Wait until truly clean
        wait_clean()

    def read_log(self):
        log_path = os.path.join(self.base_dir, "test/server_bench.log")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""


# ── MTP Detection ──────────────────────────────────────────────

def extract_mtp_stats(log_text):
    """Extract MTP draft statistics from llama-server log."""
    import re
    stats = {}
    for line in log_text.splitlines():
        low = line.lower()
        if "accept" in low and "rate" in low:
            try:
                if "acceptance rate" in low:
                    parts = line.split("acceptance rate")
                    if len(parts) > 1:
                        rate_str = parts[1].strip().lstrip("=").strip().rstrip("%")
                        stats["acceptance_rate"] = float(rate_str)
                if "n_accept" in low or "n_draft" in low or "n draft" in low:
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
    data_file = os.path.join(os.path.dirname(os.path.abspath(script_path)), "test_bench_data.txt")
    with open(data_file, "r", encoding="utf-8") as f:
        return f.read()


def make_prompt(text, target_tokens):
    target_chars = int(target_tokens * CHARS_PER_TOKEN)
    truncated = text[:target_chars]
    actual_tokens_est = len(truncated) / CHARS_PER_TOKEN
    prompt = f"{truncated}\n\n---\nSummarize the above content in 2-3 sentences."
    return prompt, int(actual_tokens_est)


# ── SSE Benchmark ──────────────────────────────────────────────

def run_test(server, prompt, prompt_tokens_est, alias,
             request_timeout=DEFAULT_REQUEST_TIMEOUT):
    """Send chat completion, parse SSE, return metrics dict."""
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
        f"{api_base}/chat/completions", data=payload, headers=headers, method="POST",
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
        return {"error": f"URL Error: {e}", "elapsed_s": round(time.time() - t0, 2)}
    except Exception as e:
        return {"error": f"Exception: {e}", "elapsed_s": round(time.time() - t0, 2)}

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

    log_text = server.read_log()
    mtp = extract_mtp_stats(log_text)
    if mtp:
        result["mtp_draft"] = mtp.get("n_draft")
        result["mtp_accept"] = mtp.get("n_accept")
        result["mtp_rate"] = mtp.get("acceptance_rate")

    return result


# ── CSV ────────────────────────────────────────────────────────

CSV_FIELDS = ["test", "prompt_tokens", "completion_tokens", "ttft_s",
              "prefill_tps", "gen_tps", "mtp_rate", "mtp_draft", "mtp_accept",
              "elapsed_s", "error"]


def save_csv(results, csv_path):
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)


def print_summary(results):
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
