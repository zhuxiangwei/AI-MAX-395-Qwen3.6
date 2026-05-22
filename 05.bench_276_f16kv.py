#!/usr/bin/env python3
"""05.bench_276_f16kv.py — 27B Dense Q6 F16 KV full context benchmark.

Tests 276 (27B Dense Q6) at p128/p4K/p32K/p64K/p128K/p256K.
F16 KV cache, UB=512.

Usage (on inference machine):
    LLM_BASE_DIR=/home/zxw LLM_API_KEY=xxx python3 -u 05.bench_276_f16kv.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchlib

# ── Configuration ──────────────────────────────────────────────
_BASE_DIR = os.environ.get("LLM_BASE_DIR", "/home/user")
MODEL_PATH = os.path.join(_BASE_DIR, "model/Qwen3.6-27B-UD-Q6_K_XL.gguf")
CSV_FILE = os.path.join(_BASE_DIR, "test/bench_276_f16kv.csv")
API_KEY = os.environ.get("LLM_API_KEY", "")

ALIAS = "276"
UBATCH = 512

TEST_POINTS = [
    ("p128",   128),
    ("p4K",    4096),
    ("p32K",   32768),
    ("p64K",   65536),
    ("p128K",  131072),
    ("p256K",  262144),
]


def main():
    print("=" * 64)
    print("  27B Dense Q6 — F16 KV Full Context Benchmark")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    if not API_KEY:
        print("ERROR: LLM_API_KEY environment variable not set. Aborting.")
        sys.exit(1)

    print("\n[INIT] Loading prompt data...")
    text = benchlib.load_prompt_data(__file__)
    print(f"  Data: {len(text)} chars, ~{len(text)/benchlib.CHARS_PER_TOKEN:.0f} tokens")

    benchlib.disable_router_service()
    benchlib.kill_all_llama()

    results = []
    server = benchlib.LlamaServer(
        model_path=MODEL_PATH, alias=ALIAS, base_dir=_BASE_DIR,
        api_key=API_KEY, ubatch=UBATCH,
    )

    try:
        for i, (name, target_tok) in enumerate(TEST_POINTS):
            print(f"\n{'─' * 64}")
            print(f"  [{i+1}/{len(TEST_POINTS)}] {name} (target ~{target_tok} tokens)")
            print(f"{'─' * 64}")

            if not server.start():
                print(f"  [FAIL] Could not start server, skipping {name}")
                results.append({"test": name, "error": "server start failed"})
                continue

            prompt, est_tokens = benchlib.make_prompt(text, target_tok)
            print(f"  Prompt: {len(prompt)} chars, ~{est_tokens} tokens")

            print(f"  Running test (streaming, no max_tokens, timeout=7200s)...")
            result = benchlib.run_test(server, prompt, est_tokens, ALIAS,
                                       request_timeout=7200)
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
                mtp = result.get("mtp_rate", "—")
                print(f"  [OK] prompt={pt}, completion={ct}, ttft={ttft}s")
                print(f"       prefill={pf} t/s, gen={gf} t/s, mtp={mtp}%, total={result['elapsed_s']}s")

            server.stop()
            benchlib.save_csv(results, CSV_FILE)
            print(f"  CSV saved to {CSV_FILE}")

    finally:
        server.stop()
        print("\n[CLEANUP] Re-enabling llm-router service...")
        benchlib.enable_router_service()

    benchlib.print_summary(results)
    print(f"\n  Results: {CSV_FILE}")


if __name__ == "__main__":
    main()
