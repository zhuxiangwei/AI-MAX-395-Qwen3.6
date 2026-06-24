#!/usr/bin/env python3
"""06.bench_apex_b.py — APEX I-Balanced (24.3GB, Q5_K_M/Q4_K_M mixed) full benchmark.

⚠ ARCHIVED: Model file removed (2026-06-12). This script is preserved for
reference only. Do not run — model file no longer exists on server.

Tests APEX I-Balanced at p128/p4K/p32K/p64K/p128K/p256K.
F16 KV UB=256 (baseline) + UB=512.

Usage:
    LLM_BASE_DIR=/home/zxw LLM_API_KEY=xxx python3 -u 06.bench_apex_b.py
    python3 -u 06.bench_apex_b.py --ub 256
"""

import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchlib

_BASE_DIR = os.environ.get("LLM_BASE_DIR", "/home/user")
MODEL_PATH = os.path.join(_BASE_DIR, "model/Qwen3.6-35B-A3B-APEX-MTP-I-Balanced.gguf")
MMPROJ_PATH = os.path.join(_BASE_DIR, "model/mmproj-F16.gguf")
API_KEY = os.environ.get("LLM_API_KEY", "")
ALIAS = "apex-b"

CONFIGS = [("f16", [256, 512])]

TEST_POINTS = [
    ("p128", 128), ("p4K", 4096), ("p32K", 32768),
    ("p64K", 65536), ("p128K", 131072), ("p256K", 262144),
]
TIMEOUT_MAP = {"p128": 300, "p4K": 300, "p32K": 600, "p64K": 1200, "p128K": 3600, "p256K": 7200}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kv", choices=["f16", "q8_0", "all"], default="all")
    parser.add_argument("--ub", type=int, nargs="*", default=None)
    args = parser.parse_args()

    run_plan = []
    for kv, ubs in CONFIGS:
        if args.kv != "all" and args.kv != kv:
            continue
        for ub in ubs:
            if args.ub is None or ub in args.ub:
                run_plan.append((kv, ub))

    print("=" * 64)
    print("  APEX I-Balanced (24.3GB) — Full Benchmark")
    for kv, ub in run_plan:
        print(f"    KV={kv}, UB={ub}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    if not API_KEY:
        print("ERROR: LLM_API_KEY not set"); sys.exit(1)
    if not run_plan:
        print("ERROR: No configs to test"); sys.exit(1)

    text = benchlib.load_prompt_data(__file__)
    print(f"  Data: {len(text)} chars, ~{len(text)/benchlib.CHARS_PER_TOKEN:.0f} tokens")

    benchlib.acquire_lock("apex-b")
    benchlib.disable_router_service()
    benchlib.kill_all_llama()
    benchlib.wait_clean()

    all_results = {}

    try:
        for kv, ub in run_plan:
            kv_tag = "f16kv" if kv == "f16" else "q8kv"
            csv_file = os.path.join(_BASE_DIR, f"test/bench_apex_b_{kv_tag}_ub{ub}.csv")

            print(f"\n{'═' * 64}")
            print(f"  KV={kv}, UB={ub}")
            print(f"{'═' * 64}")

            results = []
            server = benchlib.LlamaServer(
                model_path=MODEL_PATH, alias=ALIAS, base_dir=_BASE_DIR,
                api_key=API_KEY, ubatch=ub, cache_type_k=kv, cache_type_v=kv,
                mmproj_path=MMPROJ_PATH,
            )

            try:
                for i, (name, target_tok) in enumerate(TEST_POINTS):
                    timeout = TIMEOUT_MAP.get(name, 7200)
                    test_name = f"ub{ub}_{name}"
                    print(f"\n{'─' * 64}")
                    print(f"  [{kv} UB={ub}] [{i+1}/{len(TEST_POINTS)}] {name}")
                    print(f"{'─' * 64}")

                    if not server.start():
                        print(f"  [FAIL] Server start failed, skipping {name}")
                        results.append({"test": test_name, "error": "server start failed"})
                        continue

                    prompt, est_tokens = benchlib.make_prompt(text, target_tok)
                    if target_tok >= 128000:
                        print(f"  ⚠ Timeout={timeout}s, this will take a while.")

                    result = benchlib.run_test(server, prompt, est_tokens, ALIAS, request_timeout=timeout)
                    result["test"] = test_name
                    results.append(result)

                    if "error" in result:
                        print(f"  [FAIL] {result['error']}")
                    else:
                        pf = result.get("prefill_tps", "?")
                        gf = result.get("gen_tps", "?")
                        mtp = result.get("mtp_rate", "—")
                        print(f"  [OK] pf={pf}, gen={gf}, mtp={mtp}%, total={result['elapsed_s']}s")

                    server.stop()
                    benchlib.kill_all_llama()
                    benchlib.wait_clean()
                    benchlib.save_csv(results, csv_file)

            finally:
                benchlib.kill_all_llama()
                benchlib.wait_clean()

            all_results[(kv, ub)] = results
            benchlib.print_summary(results)

    finally:
        benchlib.release_lock("apex-b")
        print("\n  Do NOT re-enable router service — re-enable manually when all tests done.")

    print(f"\n{'═' * 80}")
    print("  Cross-Config Comparison")
    print(f"{'═' * 80}")
    for name, _ in TEST_POINTS:
        vals = []
        for (kv, ub), results in all_results.items():
            for r in results:
                if r.get("test", "").endswith(f"_{name}") and "error" not in r:
                    vals.append(f"KV={kv} UB{ub}: gen={r.get('gen_tps','?')}, pf={r.get('prefill_tps','?')}")
                    break
        if vals:
            print(f"  {name}: {' | '.join(vals)}")


if __name__ == "__main__":
    main()
