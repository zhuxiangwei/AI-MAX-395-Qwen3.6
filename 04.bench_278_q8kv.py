#!/usr/bin/env python3
"""04.bench_278_q8kv.py — 27B Dense Q8 Q8_0 KV + UB sweep benchmark.

Tests 278 (27B Dense Q8) at p128/p4K/p32K/p64K/p128K/p256K
with Q8_0 KV cache across multiple UB values (256/512/1024).

Usage (on inference machine):
    LLM_BASE_DIR=/home/zxw LLM_API_KEY=xxx python3 -u 04.bench_278_q8kv.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchlib

# ── Configuration ──────────────────────────────────────────────
_BASE_DIR = os.environ.get("LLM_BASE_DIR", "/home/user")
MODEL_PATH = os.path.join(_BASE_DIR, "model/Qwen3.6-27B-UD-Q8_K_XL.gguf")
API_KEY = os.environ.get("LLM_API_KEY", "")

ALIAS = "278"

# UB values to sweep (2048+ likely crash for 27B Dense)
UB_VALUES = [256, 512, 1024]

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
    print("  27B Dense Q8 — Q8_0 KV + UB Sweep Benchmark")
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

    all_results = {}

    try:
        for ub in UB_VALUES:
            csv_file = os.path.join(_BASE_DIR, f"test/bench_278_q8kv_ub{ub}.csv")
            results = []

            print(f"\n{'=' * 64}")
            print(f"  UB={ub} — Q8_0 KV Cache")
            print(f"{'=' * 64}")

            server = benchlib.LlamaServer(
                model_path=MODEL_PATH, alias=ALIAS, base_dir=_BASE_DIR,
                api_key=API_KEY, ubatch=ub,
                cache_type_k="q8_0", cache_type_v="q8_0",
            )

            for i, (name, target_tok) in enumerate(TEST_POINTS):
                test_name = f"ub{ub}_{name}"
                print(f"\n{'─' * 64}")
                print(f"  [UB={ub}] {name} (target ~{target_tok} tokens)")
                print(f"{'─' * 64}")

                if not server.start():
                    print(f"  [FAIL] Could not start server, skipping")
                    results.append({"test": test_name, "error": "server start failed"})
                    break

                prompt, est_tokens = benchlib.make_prompt(text, target_tok)
                print(f"  Prompt: {len(prompt)} chars, ~{est_tokens} tokens")

                print(f"  Running test (streaming, no max_tokens, timeout=7200s)...")
                result = benchlib.run_test(server, prompt, est_tokens, ALIAS,
                                           request_timeout=7200)
                result["test"] = test_name
                results.append(result)

                if "error" in result:
                    print(f"  [FAIL] {result['error']}")
                    server.stop()
                    break
                else:
                    pt = result.get("prompt_tokens", "?")
                    ct = result.get("completion_tokens", "?")
                    pf = result.get("prefill_tps", "?")
                    gf = result.get("gen_tps", "?")
                    mtp = result.get("mtp_rate", "—")
                    print(f"  [OK] prefill={pf} t/s, gen={gf} t/s, mtp={mtp}%, total={result['elapsed_s']}s")

                server.stop()
                benchlib.save_csv(results, csv_file)

            all_results[ub] = results
            print(f"  UB={ub} results: {csv_file}")

    finally:
        print("\n[CLEANUP] Re-enabling llm-router service...")
        benchlib.enable_router_service()

    print(f"\n{'=' * 80}")
    print("  27B Dense Q8 Q8_0 KV — Combined Summary")
    print(f"{'=' * 80}")
    for ub, results in all_results.items():
        print(f"\n  UB={ub}:")
        benchlib.print_summary(results)


if __name__ == "__main__":
    main()
