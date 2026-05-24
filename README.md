# Strix Halo LLM Deploy — Qwen3.6

**[English](./README.md)** | **[中文](./README.zh-CN.md)**

Deploy Qwen3.6 large language models on AMD Ryzen AI Max+ 395 (Strix Halo) with llama.cpp + Vulkan, and expose the inference API to the internet via SSH reverse tunnel + Nginx HTTPS.

---

## Performance Benchmarks

All benchmarks measured on FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9297 Vulkan).

### 35B-A3B MoE (Q8_K_XL, alias `358`)

**The primary model — fastest generation, stable at 256K context.** ✅ *Testing complete.*

MoE activates only 3B of 35B params per token → fastest generation. All speeds measured via API `timings` (server-side, excludes network latency). Gen speed includes thinking tokens (real usage).

**Optimal config:** F16 KV cache. **UB=512 for ≤128K** (prefill +14~22%), **UB=256 for 256K** (total elapsed -15%). Q8_0 KV has no advantage for MoE — Vulkan FA dequantization overhead exceeds bandwidth savings.

#### F16 KV Cache — UB Sweep (128/256/512/1024)

**Gen speed (t/s):**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 54.8 | **54.4** | 52.8 | 51.6 |
| p4K | 52.4 | **56.6** | 52.1 | 52.9 |
| p32K | 46.1 | **46.9** | 45.3 | 46.2 |
| p64K | 43.7 | **45.5** | 44.3 | 38.6 |
| p128K | —* | **36.5** | 36.0 | 37.1 |
| p256K | —* | 28.4 | **29.4** | 29.2 |

> *UB=128 p128K/p256K testing in progress.*

**Prefill speed (t/s):**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 354.4 | 340.2 | **351.9** | 344.4 |
| p4K | 523.2 | 391.3 | 474.2 | **492.7** |
| p32K | 425.1 | **520.1** | 634.4 | **662.1** |
| p64K | 353.7 | 448.1 | **542.2** | 531.9 |
| p128K | —* | **344.6** | 392.5 | 287.1 |
| p256K | —* | **238.2** | 207.8 | 132.3 |

> *UB=128 p128K/p256K testing in progress.*

**TTFT (seconds):**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 0.449s | **0.37s** | **0.36s** | 0.37s |
| p4K | 14.69s | 10.5s | 8.64s | **8.31s** |
| p32K | 85.9s | 63.0s | 51.65s | **49.49s** |
| p64K | 196.0s | 146.2s | **120.9s** | 123.2s |
| p128K | —* | 380.4s | **333.9s** | 456.5s |
| p256K | —* | **1015.0s** | 1163.6s | 1827.6s |

> *UB=128 p128K/p256K testing in progress.*

**Total elapsed time (seconds):**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 10.79s | **10.23s** | **10.04s** | 11.01s |
| p4K | 33.42s | 28.28s | **27.70s** | 27.99s |
| p32K | 98.51s | 76.01s | **65.17s** | 69.89s |
| p64K | 216.45s | 168.82s | 146.27s | **140.54s** |
| p128K | —* | 406.57s | **356.37s** | 485.81s |
| p256K | —* | **1040.83s** | 1200.3s | 1862.44s |

> *UB=128 p128K/p256K testing in progress.*

> ⚠️ Elapsed time depends on completion token count (varies per run due to thinking). Compare within same UB sweep only; do not compare elapsed across different test runs. Prefill/gen/TTFT are stable metrics.

**Findings:**

1. **UB=512 is optimal for ≤128K context** — prefill +14~22% vs UB=256, TTFT -12~18%
2. **UB=256 remains optimal for 256K context** — p256K prefill 13% faster, TTFT 13% faster vs UB=512
3. **UB=1024 degrades severely at p128K+** — p256K prefill drops to 132 t/s (-44%), TTFT balloons to 1828s (+80% vs UB=256)
4. **UB=128 is suboptimal for 35B MoE** — MTP hit rate drops from ~86% to ~65%, hurting gen speed; prefill is slower than UB=256/512 at p32K+. Unlike 27B Dense (where UB=128 unlocks F16 KV at 256K), 35B MoE already works at UB=256/512
5. **Gen speed is consistent across UB=256~1024** — within 1~2 t/s, not a differentiator; UB=128 gen is slower due to MTP degradation
6. **No Vulkan crashes at any UB** — F16 KV is stable up to 256K context

#### Q8_0 KV Cache — UB Sweep (512/1024/2048)

Q8_0 KV cache tested across 3 UB values, compared against F16 KV UB=256 baseline.

> Note: The F16 ub=256 baseline in this table was measured during the same test session as the Q8_0 data (API timings), so values may differ slightly from the main F16 KV table above (different session, client-side measurement).

**Prefill speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|--------------|--------------|
| p128 | 355.7 | **364.2** | 297.9 | 338.2 |
| p4K | 389.7 | 468.8 | **480.0** | 450.0 |
| p32K | 520.7 | 544.9 | **589.0** | 576.1 |
| p64K | **452.5** | 421.3 | 450.8 | 440.4 |
| p128K | **346.4** | 287.5 | 298.7 | 295.2 |
| p256K | **239.2** | 199.9 | 188.2 | 185.8 |

**Gen speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|--------------|--------------|
| p128 | **54.8** | 51.6 | 53.5 | 52.5 |
| p4K | **55.1** | 51.3 | 50.2 | 52.7 |
| p32K | 45.4 | 45.3 | **46.1** | 43.9 |
| p64K | **43.8** | 43.7 | 40.7 | 41.2 |
| p128K | **35.6** | 34.0 | 33.3 | 33.3 |
| p256K | **27.7** | 24.3 | 25.4 | 25.9 |

**Total elapsed time (seconds):**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|--------------|--------------|
| p128K | **404** | 477 | 469 | 468 |
| p256K | **1041** | 1352 | 1321 | 1338 |

> UB=2048 p256K completed successfully (Q8_0 KV reduces VRAM peak vs F16 KV). All Q8_0 configs slower than F16 KV UB=256 at 256K. Elapsed = TTFT + generation time. ⚠️ Elapsed depends on completion token count; do not compare across test runs.

**Findings:**

1. **Q8_0 KV UB=1024 is the best among Q8_0 configs** — fastest prefill at p4K–p128K, shortest total elapsed at p128K/p256K
2. **Even the best Q8_0 config (ub=1024) loses to F16 KV ub=256 at p64K+** — prefill -2~21%, gen -7~9%
3. **Q8_0 KV has no advantage for 35B MoE** — Vulkan FA dequantization overhead exceeds the bandwidth savings from Q8_0 compression; MoE's sparse KV cache (3B active params) means limited bandwidth to save
4. **UB=2048 p256K completed without crash** — Q8_0 KV reduces VRAM peak vs F16 KV, but still slower than F16 KV UB=256
5. **Conclusion: F16 KV UB=512 for ≤128K, UB=256 for 256K.** Q8_0 KV is not recommended for 35B MoE.

### 27B Dense Q8 (Q8_K_XL, alias `278`)

Dense architecture — all 27B params active per token. Gen speed slower than Q6/Q4, but Q8_0 KV cache unlocks 256K context and dramatically improves long-context prefill. **Recommended config: Q8_0 KV cache + ub=512** — fastest at p64K–p256K, enables 256K context (33 min vs timeout).

**F16 KV cache (ub=256):**

| Prompt Size | Gen Speed | Prefill Speed | TTFT |
|-------------|-----------|---------------|------|
| 128 tokens | 13.1 t/s | 115.2 t/s | 1.1s |
| 4K tokens | 11.9 t/s | 133.6 t/s | 30.6s |
| 32K tokens | 11.7 t/s | 174.6 t/s | 187.7s |
| 64K tokens | 11.7 t/s | 110.0 t/s | 595.6s |
| 128K tokens | 10.0 t/s | 49.8 t/s | 2633.1s |
| 256K tokens | — | — | ❌ timeout (7200s) |

> Config: `-c 262144 -b 4096 -ub 256 -t 8`, F16 KV cache, thinking enabled. F16 KV at 256K context exceeds 7200s timeout — model never reaches first token.

#### Q8_0 KV Cache + UB Sweep

Q8_0 KV cache tested across 3 UB values (256–1024), compared against F16 KV UB=256 baseline. UB≥2048 crashes at 128K+ context and is excluded.

**Prefill speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128 | 115.2 | 115.8 | 61.1 | 61.0 |
| p4K | 133.6 | 130.1 | 125.2 | 126.3 |
| p32K | 174.6 | 172.3 | **204.9** | **211.9** |
| p64K | 110.0 | 151.1 | **264.3** | 261.8 |
| p128K | 49.8 | 115.8 | **185.1** | 115.3 |
| p256K | ❌ | 80.8 | **138.6** | 136.7 |

**Gen speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128 | **13.1** | 12.5 | 12.0 | 12.5 |
| p4K | **11.9** | 12.7 | 13.0 | 12.7 |
| p32K | **11.7** | 11.7 | 11.1 | 11.1 |
| p64K | **11.7** | 10.9 | 10.4 | 10.0 |
| p128K | **10.0** | 9.5 | 9.3 | 8.9 |
| p256K | ❌ | **7.2** | 6.8 | 6.7 |

**TTFT (seconds):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128 | 1.1s | 1.1s | 2.1s | 2.1s |
| p4K | 30.6s | 31.5s | 32.7s | 32.4s |
| p32K | 187.7s | 190.2s | 160.0s | **154.6s** |
| p64K | 595.6s | 433.8s | **248.0s** | 250.4s |
| p128K | 2633.1s | 1132s | **708.3s** | 1136.9s |
| p256K | ❌ | 2994.1s | **1891.4s** | 1917.1s |

**Total elapsed time (seconds):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128K | 2716 | 1231 | **794** | 1224 |
| p256K | ❌ | 3164 | **1983** | 2040 |

**Findings:**

1. **UB=512 is the optimal choice for 27B Dense Q8_0 KV** — fastest TTFT and total time at p64K–p256K; p64K prefill +75% vs UB=256
2. **UB=1024 outperforms UB=256 only at p256K prefill** (+69%), but underperforms UB=512 at p128K TTFT by 60% (1137s vs 708s)
3. **Q8_0 KV makes 256K context viable** — F16 KV times out at 256K; Q8_0 KV UB=512 completes in 33 min
4. **Q8_0 KV dramatically improves long-context prefill** — p128K: +271% vs F16 (185 vs 50); p64K: +140% vs F16 (264 vs 110)
5. **UB≥2048 Vulkan crash** — UB=2048 crashes at p256K; 27B Dense has tighter VRAM headroom than 35B MoE
6. **Short prompt prefill anomaly** — Q8_0 KV UB≥512 drops p128 prefill from 116→61 t/s (Vulkan Dense large KV cache + high UB slow path)



### 27B Dense Q6 (Q6_K_XL, alias `276`)

Dense model at Q6 quantization. **F16 KV cache OOMs at 64K+ with UB≥512**, but **UB=128 unlocks F16 KV through p256K**. **Recommended config: Q8_0 KV cache + ub=512** — all 6 test points pass including p256K, fastest overall. **Alternative: F16 KV + UB=128** — unlocks p64K–p256K, but slower than Q8_0 KV.

#### F16 KV Cache

**UB=512 (short-context only):**

| Prompt Size | Gen Speed | Prefill Speed | TTFT | Status |
|-------------|-----------|---------------|------|--------|
| 128 tokens | 16.5 t/s | 123.3 t/s | 1.03s | ✅ |
| 4K tokens | 16.4 t/s | 129.4 t/s | 31.6s | ✅ |
| 32K tokens | 16.0 t/s | 136.3 t/s | 240.5s | ✅ |
| 64K tokens | — | — | — | ❌ timeout |
| 128K tokens | — | — | — | ❌ OOM |
| 256K tokens | — | — | — | ❌ OOM |

> Config: `-c 262144 -b 4096 -ub 512 -t 8`, F16 KV cache. F16 KV + UB=512 exceeds VRAM at 64K+ context.

**UB=128 supplement (unlocks p64K–p256K):**

| Prompt | Gen Speed | Prefill Speed | TTFT | Elapsed |
|--------|-----------|---------------|------|---------|
| p64K | 13.6 t/s | 163.9 t/s | 423s | 470s |
| p128K | 11.8 t/s | 117.2 t/s | 1158s | 1229s |
| p256K | 9.5 t/s | 44.7 t/s | 5595s | 5671s |

**UB=256 supplement:**

| Prompt | Gen Speed | Prefill Speed | TTFT | Elapsed |
|--------|-----------|---------------|------|---------|
| p64K | 14.1 t/s | 120.0 t/s | 578s | 651s |
| p128K | 12.7 t/s | 52.4 t/s | 2589s | 2680s |
| p256K | — | — | — | ❌ timeout |

> **UB=128 finding:** Reducing UB from 512→128 unlocks F16 KV at 64K–256K context. UB=128 prefill is 27~124% faster than UB=256 at p64K+ (163.9 vs 120.0 at p64K, 117.2 vs 52.4 at p128K). However, Q8_0 KV UB=512 still outperforms F16 KV UB=128 in generation speed and total elapsed time at 256K.

#### Q8_0 KV Cache + UB Sweep

**Best config: Q8_0 KV + UB=512** — fastest TTFT at p64K–p256K, all 6 points pass.

| Prompt | Q8_0 UB=512 PF | Q8_0 UB=512 Gen | Q8_0 UB=512 TTFT | Q8_0 UB=1024 PF | Q8_0 UB=1024 Gen | Q8_0 UB=1024 TTFT |
|--------|----------------|-----------------|------------------|-----------------|------------------|-------------------|
| p128 | 122.3 | 17.5 | 1.0s | 121.1 | 17.6 | 1.0s |
| p4K | 128.1 | 15.4 | 32.0s | 126.3 | 16.4 | 32.4s |
| p32K | **173.7** | 15.2 | **188.6s** | 176.3 | 15.1 | 185.8s |
| p64K | **151.3** | 13.2 | **433.1s** | 150.8 | 13.0 | 434.6s |
| p128K | **115.3** | 11.6 | **1136.9s** | 113.2 | 12.1 | 1157.4s |
| p256K | **80.2** | 8.0 | **3016.4s** | 78.1 | 8.6 | 3096.2s |

**Total elapsed time (seconds):**

| Prompt | Q8_0 UB=512 | Q8_0 UB=1024 |
|--------|-------------|--------------|
| p128K | **1227** | 1239 |
| p256K | **3111** | 3219 |

**Findings:**

1. **Q8_0 KV UB=512 is optimal** — fastest TTFT and total elapsed at all long-context sizes
2. **F16 KV UB=512 is not viable beyond 32K** — p64K times out, p128K/p256K OOM
3. **F16 KV UB=128 unlocks p64K–p256K** — but still slower than Q8_0 KV UB=512 at 256K (5671s vs 3111s elapsed)
4. **UB=128 vs UB=256 for F16 KV** — UB=128 is 27~124% faster prefill at p64K+; UB=256 times out at p256K
5. **Q8_0 KV UB=512 vs 1024: marginal difference** — UB=512 slightly faster at p64K+; UB=1024 slightly faster prefill at p32K
6. **256K context viable with Q8_0 KV** — p256K completes in ~52 min (UB=512)

### 27B Dense Q4 (Q4_K_XL, alias `274`)

Dense model at Q4 quantization — smallest model, fastest generation. **F16 KV cache only works up to 4K with UB=1024**, but **UB=128 unlocks F16 KV through p256K**. **Recommended config: Q8_0 KV cache + ub=1024** — all 6 test points pass including p256K, fastest overall. **Alternative: F16 KV + UB=128** — unlocks p32K–p256K, but slower than Q8_0 KV.

#### F16 KV Cache

**UB=1024 (short-context only):**

| Prompt Size | Gen Speed | Prefill Speed | TTFT | Status |
|-------------|-----------|---------------|------|--------|
| 128 tokens | 23.4 t/s | 145.8 t/s | 0.87s | ✅ |
| 4K tokens | 22.7 t/s | 153.3 t/s | 26.7s | ✅ |
| 32K+ | — | — | — | ❌ OOM |

> Config: `-c 262144 -b 4096 -ub 1024 -t 8`, F16 KV cache. F16 KV cache at 32K+ context exceeds available VRAM even with Q4's smaller model footprint.

**UB=128 supplement (unlocks p32K–p256K):**

| Prompt | Gen Speed | Prefill Speed | TTFT | Elapsed |
|--------|-----------|---------------|------|---------|
| p32K | 21.4 t/s | 231.2 t/s | 158s | 217s |
| p64K | 19.3 t/s | 194.2 t/s | 357s | 408s |
| p128K | 15.2 t/s | 134.6 t/s | 1008s | 1077s |
| p256K | 12.1 t/s | 47.6 t/s | 5258s | 5325s |

**UB=256 supplement:**

| Prompt | Gen Speed | Prefill Speed | TTFT | Elapsed |
|--------|-----------|---------------|------|---------|
| p32K | 20.4 t/s | 239.7 t/s | 152s | 204s |
| p64K | 18.7 t/s | 134.8 t/s | 514s | 562s |
| p128K | 15.8 t/s | 55.2 t/s | 2455s | 2490s |
| p256K | — | — | — | ❌ timeout |

> **UB=128 finding:** Reducing UB from 1024→128 unlocks F16 KV at 32K–256K context. UB=128 is dramatically faster than UB=256 at p64K+ (prefill +44~144%), and is the only F16 KV config that completes p256K. However, Q8_0 KV UB=1024 still outperforms in total elapsed time at 256K (2994s vs 5325s).

#### Q8_0 KV Cache + UB Sweep

**Best config: Q8_0 KV + UB=1024** — all 6 test points pass. UB=2048 also works up to p128K but crashes at p256K.

| Prompt | Q8_0 UB=1024 PF | Q8_0 UB=1024 Gen | Q8_0 UB=1024 TTFT | Q8_0 UB=2048 PF | Q8_0 UB=2048 Gen | Q8_0 UB=2048 TTFT |
|--------|-----------------|------------------|-------------------|-----------------|------------------|-------------------|
| p128 | 145.3 | 23.9 | 0.87s | 148.1 | 24.1 | 0.86s |
| p4K | 155.4 | 25.2 | 26.4s | 147.5 | 23.6 | 27.8s |
| p32K | 206.2 | 20.8 | 158.9s | 204.3 | 20.1 | 160.4s |
| p64K | 171.2 | 17.8 | 382.8s | 171.6 | 18.3 | 381.9s |
| p128K | 123.9 | 14.3 | 1058.0s | 125.6 | 14.6 | 1043.3s |
| p256K | 82.9 | 10.0 | 2916.5s | ❌ | ❌ | ❌ Vulkan crash |

**Q8_0 KV p256K UB=128 vs UB=256 supplement:**

| UB | Prefill | Gen | TTFT | Elapsed |
|----|---------|-----|------|---------|
| 128 | 78.2 t/s | 10.3 t/s | 3198s | 3276s |
| 256 | 91.1 t/s | 10.5 t/s | 2746s | 2834s |

> UB=256 is faster than UB=128 for Q8_0 KV at p256K. UB=1024 remains optimal overall for Q8_0 KV.

**Total elapsed time (seconds):**

| Prompt | Q8_0 UB=1024 | Q8_0 UB=2048 |
|--------|--------------|--------------|
| p128K | 1124 | 1100 |
| p256K | **2994** | ❌ crash |

**Findings:**

1. **Q8_0 KV UB=1024 is the best overall config** — all 6 points pass, p256K in ~50 min
2. **F16 KV UB=1024 is impractical beyond p4K** — but UB=128 unlocks p32K–p256K (see below)
3. **F16 KV UB=128 unlocks p32K–p256K** — but Q8_0 KV UB=1024 still wins at p256K (2994s vs 5325s elapsed)
4. **UB=2048 crashes at p256K** — same Vulkan VRAM limit pattern as other models
5. **27B Q4 is the fastest Dense model** — gen ~10–25 t/s vs Q6's 8–18 t/s vs Q8's 7–13 t/s
6. **UB=128 is the "unlock key" for F16 KV** — enables F16 KV at context lengths where higher UB values OOM or timeout; same pattern observed in Q6

### Cross-Model Comparison (Best KV + Best UB per Model)

| Prompt | 35B MoE Q8 (UB=512) | 27B Q8 (UB=512) | 27B Q6 (UB=512) | 27B Q4 (UB=1024) |
|--------|---------------------|----------------|-----------------|------------------|
| p128 Gen | 52.8 | 12.0 | 17.5 | 23.9 |
| p4K Gen | 52.1 | 13.0 | 15.4 | 25.2 |
| p32K Gen | 45.3 | 11.1 | 15.2 | 20.8 |
| p64K Gen | 44.3 | 10.4 | 13.2 | 17.8 |
| p128K Gen | 36.0 | 9.3 | 11.6 | 14.3 |
| p256K Gen | 29.4 | 6.8 | 8.0 | 10.0 |
| p256K Elapsed | 1200s | 1983s | 3111s | 2994s |

> Each model uses its optimal config: 35B MoE = F16 KV UB=512 (≤128K optimal), 27B Q8/Q6 = Q8_0 KV UB=512, 27B Q4 = Q8_0 KV UB=1024. Gen speeds include thinking tokens. 35B MoE p256K uses UB=256 (optimal for 256K): gen 28.4 t/s, elapsed 1041s.

---

## Optimization Parameters

### Key Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Service = server-level, INI = model-level | Clean separation; change model params without touching service file |
| Unified 256K context | `-c` only pre-allocates KV cache; no performance impact; one config for all prompt lengths |
| Per-quant differentiated ub | Higher quant = larger weights = less VRAM headroom = smaller ub for stability; UB=128 unlocks F16 KV for 27B Dense at 256K context |
| No `--cache-ram` | Pinned alloc fails on unified memory and is 4.6% slower; default prompt cache is better |
| `--reasoning-budget 8192` | Prevents thinking tokens from exhausting KV cache/VRAM; no performance cost |
| `-np 1` mandatory | MTP does not support multi-slot; 5 concurrent → 75% speed loss |
| `--spec-draft-n-max 3` | 4 is 20.6% slower than 3 |
| `-t 8` for all models | No difference vs `-t 16` with full GPU offload; t=8 runs cooler |
| No `--no-mmap` | No benefit; `--mmap` (default) + `--mlock` is the best combination |
| `-a Qwen3.6` | b9210 API requires model field in responses |
| `alias` short names | Convenient routing without symlinks; both alias and filename work |

### Usage Constraints

| Constraint | Value | Reason |
|-----------|-------|--------|
| Max concurrent slots | 1 (`-np 1`) | **Mandatory** — MTP does not support multi-slot |
| 35B MoE: max context | 256K | UB=512 optimal for ≤128K; UB=256 optimal for 256K; UB≥2048 Vulkan crash at 128K+ |
| 27B Dense: max context | 256K (Q8_0 KV or F16 KV UB=128) | Q8_0 KV UB=512 (Q8/Q6) / UB=1024 (Q4) recommended; F16 KV UB=128 also reaches 256K for Q4/Q6; F16 KV default UB times out at 256K; UB≥2048 crashes |
| Thinking mode | Enabled (`reasoning-budget=8192`) | Budget cap prevents runaway thinking tokens; no performance cost |
| Avoid concurrency | 1 request at a time | Concurrent → 75% speed loss |
| No `--cache-ram` | Don't add it | Harmful on unified memory |
| `b` must divide by `ub` | `n_batch % n_ubatch == 0` | llama.cpp requirement |

### Parameter Separation Principle

| Scope | Where | Examples |
|-------|-------|---------|
| **Server-level** | `llm-router.service` ExecStart | `--host`, `--port`, `--api-key`, `--models-dir`, `--models-max`, `--models-preset`, `--sleep-idle-seconds`, `--timeout` |
| **Model-level** | `router-preset.ini` per-model section | `n-gpu-layers`, `ctx-size`, `ubatch-size`, `threads`, `alias`, `spec-type`, `mlock`, `numa`, ... |

> Model parameters are defined **only** in the INI — never duplicated in the service file.

### Preset INI (Per-Model Parameters)

**File:** `~/model/router-preset.ini`

```ini
[Qwen3.6-35B-A3B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 1
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
threads = 8
alias = 358

[Qwen3.6-27B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 1
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 262144
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 278

[Qwen3.6-27B-UD-Q6_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 1
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 262144
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 276

[Qwen3.6-27B-UD-Q4_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 1
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 262144
batch-size = 4096
ubatch-size = 1024
threads = 8
alias = 274
```

**To change model parameters:** edit the INI file → `systemctl --user restart llm-router`

---

## Deployment Guide

### Architecture

```
┌─────────────────┐      HTTPS (443)      ┌──────────────────┐
│   Client        │ ────────────────────▶ │  Cloud Nginx     │
│  (any device)   │                       │  {your_domain}   │
└─────────────────┘                       └────────┬─────────┘
                                                  │
                                      proxy_pass 127.0.0.1:8080
                                                  │
┌─────────────────┐     SSH Reverse Tunnel        │
│  Inference Box  │ ◀─────────────────────────────┘
│  Ubuntu 26.04   │  127.0.0.1:8080 ←→ 127.0.0.1:12345
│  AMD AI Max+395 │
│  128 GB RAM     │
└─────────────────┘
```

**Key design decisions:**
- llama.cpp binds `127.0.0.1:12345` only — no direct network exposure
- Cloud server runs **only Nginx** (port 443) — no application code
- SSH reverse tunnel provides NAT traversal (home network → cloud)
- OpenAI-compatible API endpoint at `https://{your_domain}/v1/`
- **Router Mode** with per-model preset INI — automatic LRU model switching
- **Alias short names** (358/278/276/274) for convenient model selection

### Hardware

| Component | Specification |
|-----------|--------------|
| Machine | FEVM faex1 mini PC |
| APU | AMD Ryzen AI Max+ 395 (16C/32T) |
| Memory | 128 GB LPDDR5X (256-bit, unified memory) |
| Storage | 1 TB NVMe SSD |
| iGPU | Radeon 8060S (RDNA 3.5, 40 CU, 2040 MHz) |
| GTT (GPU-accessible RAM) | 120 GB (kernel param `amdgpu.gttsize=122880`) |

**Memory bandwidth:** 256-bit × 8000 MT/s ÷ 8 = **256 GB/s** theoretical, ~200 GB/s practical. Dense models are memory-bandwidth bound.

### Software

| Component | Version / Details |
|-----------|-------------------|
| Inference OS | Ubuntu 26.04 LTS |
| Cloud OS | Ubuntu 24.04.4 LTS |
| llama.cpp | b9297 (commit b22ff4b7b, Vulkan backend) |
| Build options | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` (+ BLAS/OpenMP/LTO/NATIVE) |
| Vulkan runtime | 1.4.341 |
| API protocol | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |

**Building llama.cpp:**

```bash
cd ~/llama/llama.cpp
git pull origin master                    # update source
cmake -B build --fresh \
  -DGGML_VULKAN=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

> `--fresh` resets CMake cache (recommended after version upgrades). Binary: `build/bin/llama-server`.

**Path layout on inference box:**

| Item | Path |
|------|------|
| Model files + preset INI | `$HOME/model/` |
| llama-server binary | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Router preset | `$HOME/model/router-preset.ini` |

### Model Inventory

Router Mode serves all models from `$HOME/model/`. Only one is loaded at a time (`--models-max 1`), switching via LRU on client request. Each model has an **alias** for short-name routing.

| Model | File | Alias | Quant | Arch | Size | Active Params |
|-------|------|-------|-------|------|------|---------------|
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | **358** | Q8_K_XL | **MoE** | ~37 GB | 3B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | **278** | Q8_K_XL | Dense | ~33 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | **276** | Q6_K_XL | Dense | ~25 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | **274** | Q4_K_XL | Dense | ~17 GB | 27B |

> **Alias naming convention:** 3 digits = model size + quant level. e.g. `358` = 35B Q8, `276` = 27B Q6, `274` = 27B Q4. Both alias and full filename work in the `model` field of API requests.

### 1. Cloud Nginx Configuration

**File:** `/etc/nginx/sites-available/default`

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;

    include snippets/snakeoil.conf;

    root /var/www/html;
    index index.html index.nginx-debian.html;
    server_name {your_domain};

    location / {
        try_files $uri $uri/ =404;
    }

    # LLM API endpoint (OpenAI-compatible)
    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Long timeout (LLM inference is slow, match llama-server timeout)
        proxy_read_timeout 3600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;

        # SSE streaming support
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }

    # Health check
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**Apply:** `sudo nginx -t && sudo systemctl reload nginx`

### 2. Cloud SSL Configuration

**File:** `/etc/nginx/snippets/snakeoil.conf`

```nginx
ssl_certificate /root/cert.nginx/{your_domain}.pem;
ssl_certificate_key /root/cert.nginx/{your_domain}.key;

ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers HIGH:!aNULL:!MD5;
ssl_prefer_server_ciphers on;
```

### 3. Cloud SSH Server

**File:** `/etc/ssh/sshd_config`

```sshd_config
AllowTcpForwarding yes
ClientAliveInterval 60
ClientAliveCountMax 3
# GatewayPorts no   (default — keep tunnel on 127.0.0.1 only)
```

**Apply:** `sudo systemctl restart ssh`

**Verify:** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|gatewayports"`

### 4. SSH Reverse Tunnel (systemd)

**File:** `~/.config/systemd/user/llm-tunnel.service` (user-level, no sudo needed)

```ini
[Unit]
Description=LLM SSH Reverse Tunnel
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/usr/bin/ssh \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o ConnectTimeout=10 \
    -R 8080:127.0.0.1:12345 \
    -N \
    root@{your_server_ip}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

**Tunnel port:** `-R 8080:127.0.0.1:12345` (API only)

> Note: Reverse SSH (-R 2222) has been removed. Manage the inference box via local network direct access only.

```bash
mkdir -p ~/.config/systemd/user
# Create the service file, then:
systemctl --user daemon-reload
systemctl --user enable llm-tunnel
systemctl --user start llm-tunnel
loginctl enable-linger   # survive logout
```

**Manual tunnel test (before systemd):**
```bash
# On inference box:
ssh -R 8080:127.0.0.1:12345 root@{your_server_ip} -N
# On cloud, verify:
curl http://127.0.0.1:8080/v1/models
```

**SSH key setup (passwordless):**
```bash
ssh-keygen -t ed25519 -C "llm-tunnel@faex1"
ssh-copy-id root@{your_server_ip}
```

### 5. Inference Service (systemd)

**File:** `~/.config/systemd/user/llm-router.service` (user-level, no sudo needed)

```ini
[Unit]
Description=LLM Router Service (llama-server multi-model)
After=network.target

[Service]
Type=simple
ExecStart=~/llama/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 --port 12345 \
    --api-key {your_api_key} \
    -a Qwen3.6 \
    --models-dir ~/model \
    --models-max 1 \
    --models-preset ~/model/router-preset.ini \
    --sleep-idle-seconds 600 \
    --timeout 3600
Restart=on-failure
RestartSec=10
WorkingDirectory=%h
LimitMEMLOCK=infinity

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable llm-router
systemctl --user start llm-router
loginctl enable-linger   # survive logout
```

### Model Switching

Clients specify the `model` field in API requests. Both **alias short names** and **full filenames** work. Router switches automatically (LRU, 8–17 seconds cold load):

```bash
# Using alias (recommended)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "358", ...}'

# Using full filename (also works)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "Qwen3.6-35B-A3B-UD-Q8_K_XL", ...}'
```

**QClaw integration:**

| Command | Model |
|---------|-------|
| `/model 358` | 35B-A3B Q8 (MoE, fastest) |
| `/model 278` | 27B Q8 (Dense, highest accuracy) |
| `/model 276` | 27B Q6 (Dense, balanced) |
| `/model 274` | 27B Q4 (Dense, most economical) |

### Verification Checklist

- [ ] Cloud Nginx config updated (with `/v1/` and `/health` endpoints)
- [ ] Cloud SSL certificates configured
- [ ] Cloud `sshd_config` allows TCP forwarding and keepalive
- [ ] Inference box has SSH key for passwordless login to cloud
- [ ] `llm-tunnel.service` created and **active**
- [ ] Cloud: `ss -tlnp | grep 8080` shows tunnel listening
- [ ] `llm-router.service` created and **active** (server-level params only)
- [ ] `~/model/router-preset.ini` configured with model-level params + aliases
- [ ] Cloud: `curl http://127.0.0.1:8080/v1/models` returns 4 models with aliases
- [ ] External: `curl https://{your_domain}/health` returns `OK`
- [ ] Alias routing: `curl -d '{"model":"358",...}'` routes to 35B-A3B Q8

**Quick smoke test:**
```bash
curl https://{your_domain}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{
    "model": "358",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50,
    "stream": true
  }'
```

---

*Tested on FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9297 Vulkan · 2026-05-24*
