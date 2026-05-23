#!/usr/bin/env python3
"""01.bench_358.py — 35B MoE Q8 full benchmark.

Tests 358 (35B-A3B Q8 MoE) at p128/p4K/p32K/p64K/p128K/p256K.
Covers F16 KV (UB=256/512/1024) and Q8_0 KV (UB=512/1024/2048).

Usage (on inference machine):
    LLM_BASE_DIR=/home/zxw LLM_API_KEY=xxx python3 -u 01.bench_358.py

Filter by KV type and/or UB:
    python3 -u 01.bench_358.py --kv f16 --ub 256
    python3 -u 01.bench_358.py --kv q8_0 --ub 512 1024
    python3 -u 01.bench_358.py --ub 256          # both KV types with UB=256
"""

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchlib

# ── Configuration ──────────────────────────────────────────────
_BASE_DIR = os.environ.get("LLM_BASE_DIR", "/home/user")
MODEL_PATH = os.path.join(_BASE_DIR, "model/Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf")
API_KEY = os.environ.get("LLM_API_KEY", "")

ALIAS = "358"

# Test configurations: (kv_type, [ub_values])
# F16 KV: UB=256 is baseline; UB=512/1024 for comparison
# Q8_0 KV: UB=512/1024/2048 for comparison (no benefit vs F16, kept for reference)
CONFIGS = [
    ("f16",  [256, 512, 1024]),
    ("q8_0", [512, 1024, 2048]),
]

TEST_POINTS = [
    ("p128",   128),
    ("p4K",    4096),
    ("p32K",   32768),
    ("p64K",   65536),
    ("p128K",  131072),
    ("p256K",  262144),
]

# Timeout scaling by prompt size (seconds)
TIMEOUT_MAP = {
    "p128": 300, "p4K": 300, "p32K": 600,
    "p64K": 1200, "p128K": 3600, "p256K": 7200,
}


def main():
    parser = argparse.ArgumentParser(description="01 — 35B MoE Q8 benchmark (F16 + Q8_0 KV)")
    parser.add_argument("--kv", choices=["f16", "q8_0", "all"], default="all",
                        help="KV cache type to test (default: all)")
    parser.add_argument("--ub", type=int, nargs="*", default=None,
                        help="UB values to test (default: from CONFIGS)")
    args = parser.parse_args()

    # Build run plan
    run_plan = []
    for kv, ubs in CONFIGS:
        if args.kv != "all" and args.kv != kv:
            continue
        filtered_ubs = [u for u in ubs if args.ub is None or u in args.ub]
        for ub in filtered_ubs:
            run_plan.append((kv, ub))

    print("=" * 64)
    print("  35B MoE Q8 — Full Benchmark")
    print(f"  Plan: {len(run_plan)} config(s)")
    for kv, ub in run_plan:
        print(f"    KV={kv}, UB={ub}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    if not API_KEY:
        print("ERROR: LLM_API_KEY environment variable not set. Aborting.")
        sys.exit(1)

    if not run_plan:
        print("ERROR: No configurations to test. Check --kv and --ub filters.")
        sys.exit(1)

    print("\n[INIT] Loading prompt data...")
    text = benchlib.load_prompt_data(__file__)
    print(f"  Data: {len(text)} chars, ~{len(text)/benchlib.CHARS_PER_TOKEN:.0f} tokens")

    benchlib.acquire_lock("358")
    benchlib.disable_router_service()
    benchlib.kill_all_llama()

    all_results = {}

    try:
        for kv, ub in run_plan:
            kv_tag = "f16kv" if kv == "f16" else "q8kv"
            csv_file = os.path.join(_BASE_DIR, f"test/bench_358_{kv_tag}_ub{ub}.csv")

            print(f"\n{'═' * 64}")
            print(f"  KV={kv}, UB={ub}")
            print(f"{'═' * 64}")

            results = []
            cache_k = kv if kv != "f16" else "f16"
            cache_v = kv if kv != "f16" else "f16"

            server = benchlib.LlamaServer(
                model_path=MODEL_PATH, alias=ALIAS, base_dir=_BASE_DIR,
                api_key=API_KEY, ubatch=ub,
                cache_type_k=cache_k, cache_type_v=cache_v,
            )

            try:
                for i, (name, target_tok) in enumerate(TEST_POINTS):
                    timeout = TIMEOUT_MAP.get(name, 7200)
                    test_name = f"ub{ub}_{name}"
                    print(f"\n{'─' * 64}")
                    print(f"  [{kv} UB={ub}] [{i+1}/{len(TEST_POINTS)}] {name} (~{target_tok} tokens)")
                    print(f"{'─' * 64}")

                    if not server.start():
                        print(f"  [FAIL] Could not start server, skipping {name}")
                        results.append({"test": test_name, "error": "server start failed"})
                        continue

                    prompt, est_tokens = benchlib.make_prompt(text, target_tok)
                    print(f"  Prompt: {len(prompt)} chars, ~{est_tokens} tokens")

                    if target_tok >= 128000:
                        print(f"  ⚠ This will take ~15-25 minutes. Timeout={timeout}s.")

                    print(f"  Running test (timeout={timeout}s)...")
                    result = benchlib.run_test(server, prompt, est_tokens, ALIAS,
                                               request_timeout=timeout)
                    result["test"] = test_name
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
                    benchlib.save_csv(results, csv_file)
                    print(f"  CSV saved to {csv_file}")

            finally:
                server.stop()
                # Extra safety: ensure no residual processes between configs
                benchlib.kill_all_llama()

            all_results[(kv, ub)] = results
            print(f"\n  KV={kv} UB={ub} Summary:")
            benchlib.print_summary(results)

    finally:
        benchlib.release_lock("358")
        print("\n  Do NOT re-enable router service — re-enable manually when all tests done.")

    # Cross-config comparison
    print(f"\n{'═' * 80}")
    print("  Cross-Config Comparison")
    print(f"{'═' * 80}")
    for name, _ in TEST_POINTS:
        vals = []
        for (kv, ub), results in all_results.items():
            for r in results:
                if r.get("test", "").endswith(f"_{name}") and "error" not in r:
                    vals.append(f"KV={kv} UB{ub}: gen={r.get('gen_tps', '?')}, pf={r.get('prefill_tps', '?')}, TTFT={r.get('ttft_s', '?')}")
                    break
        if vals:
            print(f"  {name}: {' | '.join(vals)}")


if __name__ == "__main__":
    main()
