#!/usr/bin/env python3
"""00.test_hello.py — Router Mode 4-model greeting test with log analysis.

Tests each model (358/278/276/274) sequentially with a simple greeting,
then reads inference machine logs via SSH to check errors, warnings, and
performance data. Waits between model switches to allow Router LRU loading.

Usage:
    python 00.test_hello.py [--api-url URL] [--api-key KEY] [--no-ssh]
"""

import os
import sys
import time
import json
import argparse
import subprocess
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────
DEFAULT_BASE_URL = os.environ.get("LLM_API_URL", "")
DEFAULT_API_KEY = os.environ.get("LLM_API_KEY", "")
MODELS = ["358", "278", "276", "274"]
MODEL_NAMES = {
    "358": "35B-A3B Q8 (MoE)",
    "278": "27B Q8 (Dense)",
    "276": "27B Q6 (Dense)",
    "274": "27B Q4 (Dense)",
}
GREETING = "Hello, please introduce yourself in one sentence."
SWITCH_WAIT = 25  # seconds to wait after model switch (LRU load time 8-17s, 27B Dense takes longer)
LOG_FLUSH_WAIT = 3  # seconds for logs to flush before reading

# SSH config for inference machine logs
SSH_KEY = os.path.expanduser(os.environ.get("LLM_SSH_KEY", ""))
SSH_HOST = os.environ.get("LLM_SSH_HOST", "")
SSH_USER = os.environ.get("LLM_SSH_USER", "")
SSH_PROXY_CMD = ""  # set via LLM_SSH_PROXY if going through a jump host
_proxy = os.environ.get("LLM_SSH_PROXY", "")
if _proxy:
    SSH_PROXY_CMD = f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no -W %h:%p {_proxy}"


# ── API Call ───────────────────────────────────────────────────
def call_model(base_url, api_key, model_id, prompt, timeout=300):
    """Send a chat completion request, return (response_dict, elapsed_seconds)."""
    try:
        import requests
    except ImportError:
        print("  [ERROR] 'requests' library not installed. Run: pip install requests")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "stream": False,
        # Thinking mode is enabled on server (reasoning-budget=8192)
        # Explicitly request thinking output so we can verify it works
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }

    t0 = time.time()
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        if resp.status_code != 200:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text[:500]
            return {"error": f"HTTP {resp.status_code}: {err_body}"}, elapsed
        return resp.json(), elapsed
    except requests.exceptions.Timeout:
        elapsed = time.time() - t0
        return {"error": f"Request timed out after {elapsed:.1f}s"}, elapsed
    except Exception as e:
        elapsed = time.time() - t0
        return {"error": str(e)}, elapsed


# ── SSH Log Reader ─────────────────────────────────────────────
def read_inference_logs(since_minutes=3):
    """SSH to inference machine and read llm-router journal logs."""
    cmd = [
        "ssh", "-i", SSH_KEY,
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=no",
    ]
    if SSH_PROXY_CMD:
        cmd += ["-o", f"ProxyCommand={SSH_PROXY_CMD}"]
    cmd += [
        f"{SSH_USER}@{SSH_HOST}",
        f"journalctl --user -u llm-router --since '{since_minutes} min ago' --no-pager 2>&1",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "[SSH timeout reading logs]"
    except Exception as e:
        return f"[SSH error: {e}]"


def analyze_logs(log_text):
    """Extract errors, warnings, and performance-relevant lines from logs."""
    errors = []
    warnings = []
    perf_lines = []
    for line in log_text.splitlines():
        low = line.lower()
        # Skip empty / info-only lines
        if not line.strip():
            continue
        if any(kw in low for kw in ["error", "fail", "crash", "device lost", "vulkan"]):
            errors.append(line.strip())
        if "warn" in low:
            warnings.append(line.strip())
        # Performance-relevant keywords
        if any(kw in low for kw in [
            "t/s", "token/s", "eval time", "load time", "unload",
            "slot", "prompt eval", "model loaded", "model unloaded",
            "sleeping", "waking", "speculative", "draft", "accept",
        ]):
            perf_lines.append(line.strip())
    return errors, warnings, perf_lines


# ── Main Test Loop ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Router Mode 4-model greeting test")
    parser.add_argument("--api-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key")
    parser.add_argument("--no-ssh", action="store_true", help="Skip SSH log reading")
    args = parser.parse_args()

    if not args.api_url:
        parser.error("--api-url is required (or set LLM_API_URL env var)")
    if not args.api_key:
        parser.error("--api-key is required (or set LLM_API_KEY env var)")


    print("=" * 64)
    print("  Router Mode 4-Model Greeting Test")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  API:  {args.api_url}")
    print("=" * 64)

    results = []

    for i, model_id in enumerate(MODELS):
        model_name = MODEL_NAMES.get(model_id, model_id)
        print(f"\n{'─' * 64}")
        print(f"  Test {i+1}/4: model={model_id} ({model_name})")
        print(f"{'─' * 64}")

        # ── Step 1: Send greeting ──
        print(f"  [1/3] Sending greeting...")
        response, elapsed = call_model(args.api_url, args.api_key, model_id, GREETING)

        # Parse response
        if "error" in response:
            print(f"  [FAIL] API Error: {response['error']}")
            results.append({
                "model": model_id, "name": model_name,
                "status": "error", "error": str(response["error"]),
                "elapsed_s": round(elapsed, 2),
            })
        else:
            choices = response.get("choices", [{}])
            msg = choices[0].get("message", {}) if choices else {}
            content = msg.get("content", "(empty)")
            thinking_content = msg.get("reasoning_content", "")
            usage = response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", "?")
            completion_tokens = usage.get("completion_tokens", "?")
            total_tokens = usage.get("total_tokens", "?")

            # Calculate speed based on total tokens (includes thinking tokens)
            speed_str = ""
            if isinstance(total_tokens, (int, float)) and elapsed > 0:
                speed = total_tokens / elapsed
                speed_str = f" (~{speed:.1f} t/s total)"

            print(f"  [OK] Response ({elapsed:.1f}s{speed_str}):")
            if thinking_content:
                print(f"     Thinking ({len(thinking_content)} chars):")
                for line in thinking_content[:200].split("\n"):
                    print(f"       {line}")
                if len(thinking_content) > 200:
                    print(f"       ... ({len(thinking_content)} chars total)")
            for line in content[:300].split("\n"):
                print(f"     {line}")
            if len(content) > 300:
                print(f"     ... ({len(content)} chars total)")
            print(f"     Tokens: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")
            if thinking_content:
                print(f"     Thinking: present ({len(thinking_content)} chars)")

            results.append({
                "model": model_id, "name": model_name,
                "status": "ok", "elapsed_s": round(elapsed, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "thinking_present": bool(thinking_content),
                "thinking_chars": len(thinking_content) if thinking_content else 0,
                "response_preview": content[:200],
            })

        # ── Step 2: Wait for log flush, then read logs ──
        if not args.no_ssh:
            print(f"  [2/3] Waiting {LOG_FLUSH_WAIT}s for log flush...")
            time.sleep(LOG_FLUSH_WAIT)

            print(f"  [2/3] Reading inference machine logs...")
            logs = read_inference_logs(since_minutes=3)
            errors, warnings, perf = analyze_logs(logs)

            if errors:
                print(f"  [!!] Errors ({len(errors)}):")
                for e in errors[:8]:
                    print(f"     {e[:160]}")
            else:
                print(f"  [OK] No errors in logs")

            if warnings:
                print(f"  [??] Warnings ({len(warnings)}):")
                for w in warnings[:5]:
                    print(f"     {w[:160]}")
            else:
                print(f"  [OK] No warnings in logs")

            if perf:
                print(f"  [PERF] Performance lines ({len(perf)}):")
                for p in perf[:12]:
                    print(f"     {p[:160]}")
            else:
                print(f"  [INFO] No performance data in logs")
        else:
            print(f"  [2/3] SSH skipped (--no-ssh)")

        # ── Step 3: Wait before next model ──
        if i < len(MODELS) - 1:
            print(f"  [3/3] Waiting {SWITCH_WAIT}s for model switch...")
            time.sleep(SWITCH_WAIT)
        else:
            print(f"  [3/3] Last model, no wait needed.")

    # ── Summary ──
    print(f"\n{'=' * 64}")
    print("  Test Summary")
    print(f"{'=' * 64}")
    print(f"  {'Model':<6} {'Name':<22} {'Status':<8} {'Time':>8} {'Tokens':>10} {'Think':>7}")
    print(f"  {'─'*6} {'─'*22} {'─'*8} {'─'*8} {'─'*10} {'─'*7}")
    for r in results:
        tokens = r.get("completion_tokens", "?")
        if tokens != "?" and r.get("prompt_tokens", "?") != "?":
            tokens = f"{r['completion_tokens']}/{r['total_tokens']}"
        think = "✓" if r.get("thinking_present") else "✗"
        print(f"  {r['model']:<6} {r['name']:<22} {r['status']:<8} "
              f"{r.get('elapsed_s', '?'):>7.1f}s {tokens:>10} {think:>7}")
    print(f"{'=' * 64}")

    # Save results JSON
    result_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
    os.makedirs(result_dir, exist_ok=True)
    result_file = os.path.join(result_dir, "00.test_hello_results.json")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {result_file}")


if __name__ == "__main__":
    main()
