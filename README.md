# Strix Halo LLM Deploy — Qwen3.6

**[English](./README.md)** | **[中文](./README.zh-CN.md)**

Deploy Qwen3.6 large language models on AMD Ryzen AI Max+ 395 (Strix Halo) with llama.cpp + Vulkan, and serve the inference API over the internet via SSH reverse tunnel + Nginx HTTPS.

---

## Performance Benchmarks

All benchmarks measured on {your_machine} (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9315 Vulkan). Speeds via API `timings` (server-side, excludes network). Gen speed includes thinking tokens.

**Benchmark environment:** CPU governor=performance, `processor.max_cstate=1`, `vm.swappiness=1`, `vm.overcommit_memory=1`, GTT 120GB, mlock=1. These system-level optimizations improve gen speed and prefill stability vs the default powersave governor.

### 35B-A3B MoE (UD-Q8_K_XL, alias `358`)

**Auxiliary model — Hermes auxiliary tasks (vision, compression, etc.).** MoE activates only 3B/35B params per token. ~50 t/s generation with vision support.

**Optimal config: F16 KV cache.** ≤128K → UB=512 (prefill +22~25%, TTFT -17~20% vs UB=256). 256K → UB=256 (elapsed -13% vs UB=512).

**Ruled out:** UB=128 (MTP 86%→65%, gen slower); UB≥1024 (p256K prefill -44%, TTFT +80%); Q8_0 KV (dequant overhead > bandwidth savings for sparse KV; all Q8_0 UBs slower than F16 UB=256); UB≥2048 (Vulkan crash at 128K+).

#### F16 KV UB=512 (optimal ≤128K)

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 56.7 | 371.0 | 0.43s |
| p4K | 56.7 | 931.4 | 8.2s |
| p32K | 50.1 | 730.1 | 50.0s |
| p64K | 46.7 | 590.7 | 117.3s |
| p128K | 38.0 | 416.2 | 325.9s |
| p256K | 28.4 | 217.6 | 1149.7s |

#### F16 KV UB=256 (optimal 256K)

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 58.2 | 427.9 | 0.37s |
| p4K | 54.6 | 746.9 | 10.3s |
| p32K | 48.7 | 590.0 | 61.9s |
| p64K | 46.9 | 485.1 | 142.9s |
| p128K | 38.0 | 363.1 | 373.6s |
| p256K | 29.3 | 250.4 | 999.2s |

> Gen speed is nearly identical across UB=256/512 (±2 t/s). UB choice mainly affects prefill/TTFT: UB=512 is faster at ≤128K; UB=256 is faster at 256K.

### 35B-A3B MoE APEX I-Quality (alias `35xq`, ~22 GB)

APEX quantization — Adaptive Precision for EXpert Models. Mixed-precision per tensor (critical layers Q6_K/Q8_0, middle expert layers Q4_K_M). ~22 GB overall (between Q4 and Q5 by size, but quality matches Q8). imatrix-calibrated with diverse data. **~48% faster than UD-Q8 + MTP, 59% file size.** Auxiliary model with mmproj for vision tasks. Reasoning is enabled by default (`reasoning-budget = 8192`); clients can disable thinking per-request via `chat_template_kwargs.enable_thinking: false`.

**Optimal config: F16 KV cache.** Same pattern as 35B UD-Q8: ≤128K → UB=512 (prefill +15~23%); 256K → UB=256 (prefill -4% vs UB=512).

#### F16 KV UB=512 (optimal ≤128K)

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 84.1 | 401.7 | 0.40s |
| p4K | 80.3 | 934.9 | 8.2s |
| p32K | 62.3 | 731.1 | 49.9s |
| p64K | 57.2 | 590.0 | 117.5s |
| p128K | 47.0 | 425.1 | 319.1s |
| p256K | 32.9 | 241.0 | 1038.2s |

#### F16 KV UB=256 (optimal 256K)

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 82.4 | 396.7 | 0.40s |
| p4K | 73.5 | 761.2 | 10.1s |
| p32K | 66.8 | 597.7 | 61.1s |
| p64K | 58.8 | 488.7 | 141.8s |
| p128K | 42.9 | 364.1 | 372.5s |
| p256K | 32.2 | 251.1 | 996.4s |

> APEX I-Quality gen speed **~48% faster** than UD-Q8 at all prompt sizes (80 vs 54 t/s). File size 21.9 GB vs 37 GB.

### 35B-A3B MoE APEX I-Balanced (alias `35xb`, ~24 GB) — **DELETED**

⚠ Model file removed (2026-06-12). Benchmark data preserved for reference.

APEX quantization — best quality-to-speed tradeoff. Mixed-precision per tensor (critical layers Q6_K/Q5_K_M, middle expert layers Q4_K_M). ~24 GB overall (between Q5 and Q6 by size). KL max 4.53 — **lowest deviation among all quantizations** (even better than Q8's 9.72). imatrix calibration reduces worst-case deviation by 68%. **Not registered in Hermes** — served by llama-server for manual API switch only.

**Optimal config: F16 KV cache, UB=512.** UB=512 is the best overall choice for ≤128K (prefill +22~25% vs UB=256). UB≥1024 degrades at ≥128K (p256K prefill -34% vs UB=512).

#### F16 KV UB=512 (historical benchmark)

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 75.2 | 377.5 | 0.42s |
| p4K | 75.7 | 903.0 | 8.51s |
| p32K | 62.9 | 706.2 | 51.71s |
| p64K | 56.1 | 575.9 | 120.35s |
| p128K | 45.3 | 417.3 | 325.07s |
| p256K | 35.8 | 240.9 | 1038.41s |

#### F16 KV UB=256 (optimal 256K)

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 78.2 | 435.3 | 0.37s |
| p4K | 78.9 | 731.9 | 10.50s |
| p32K | 65.1 | 577.9 | 63.19s |
| p64K | 56.7 | 475.7 | 145.70s |
| p128K | 44.5 | 356.7 | 380.26s |
| p256K | 32.0 | 246.9 | 1013.52s |

> APEX I-Balanced gen speed **~40% faster** than UD-Q8. Quality leader: KL max 4.53 is the best among all quantizations.
>
> **Config updates since these benchmarks** (2026-06-06): `spec-draft-n-max` 3→2 (+5~12% gen speed), `ubatch-size` 512→256 (stability at long contexts), `cache-reuse=256` (improves multi-turn), `max_cstate=1` + `governor=performance` (system-level latency reduction). These changes improve gen speed and TTFT but the UB=512 table above was measured before these updates — actual performance with current config is expected to be different.

### 27B Dense Q8 (Q8_K_XL, alias `278`)

Dense model — all 27B params active per token. Current Hermes default model.

**Config: F16 KV + UB=256 + kv-unified=1 + cache-ram=16384 + slot-prompt-similarity=0.8.**

**Ruled out:** Q8_0 KV (1.7–2× KV space vs Q4_0, no significant prefill advantage); Q4_0 KV (Vulkan dequantization overhead negates bandwidth savings); UB≥1024 (long-context prefill degradation 11–34%); UB≥2048 (Vulkan crash).

#### F16 KV UB=256 (current config)

| Prompt | Gen (t/s) | Prefill (t/s) | MTP Rate | Source |
|--------|----------|--------------|----------|--------|
| ~1K | 10.9 | 53.0 | 0.80 | Prod log† |
| ~10K | 12.8 | 167.9 | 0.86 | Prod log† |
| ~16K | 13.0 | 225.5 | 0.84 | Prod log† |
| ~20K | 14.4 | 215.5 | 0.99 | Prod log† |
| ~65K | 10.7 | 117.3 | 0.74 | Prod log† |
| ~146K | 8.5 | 42.1 | 0.68 | Prod log† |

> † Production workload log data (F16 KV, UB=256, cache-ram=16384, ~186 requests, excluding checkpoint-restore hits). MTP rate declines significantly beyond 50K context. Gen speed stable at 10–14 t/s for short/medium context, drops to ~8.5 t/s at 146K+.
>
> **Historical reference (Q8_0 KV UB=512, superseded):** p128=127.4, p4K=247.3, p32K=194.6, p64K=160.2, p128K=119.1, p256K=82.8 t/s prefill; gen 7.3–13.8 t/s.

### 27B Dense Q6 (Q6_K_XL, alias `276`)

Dense model, Q6 quantization — best balance of speed and accuracy.

**Optimal config: Q8_0 KV + UB=512.**

**Ruled out:** F16 KV UB≥512 (p64K+ OOM/timeout); F16 KV UB=128 (unlocks p256K but 2× slower elapsed than Q8_0 KV: 5671s vs 3130s); Q8_0 UB=1024 (marginally worse at p64K+); UB≥2048 (Vulkan crash).

#### Q8_0 KV UB=512

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 18.9 | 140.8 | 1.1s |
| p4K | 17.2 | 244.0 | 31.5s |
| p32K | 15.8 | 194.6 | 187.7s |
| p64K | 14.2 | 160.3 | 432.3s |
| p128K | 11.2 | 119.1 | 1139.1s |
| p256K | 8.8 | 82.7 | 3025.1s |

> p256K elapsed: 3130s (~52 min).

### 27B Dense Q4 (Q4_K_XL, alias `274`)

Dense model, Q4 quantization — fastest generation among Dense models.

**Optimal config: Q8_0 KV + UB=1024.**

**Ruled out:** F16 KV UB≥1024 (p32K+ OOM); F16 KV UB=128 (unlocks p256K but 1.8× slower elapsed: 5325s vs 2886s); Q8_0 UB≤256 (slower at p32K+); UB≥2048 (Vulkan crash at p256K).

#### Q8_0 KV UB=1024

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 26.5 | 161.9 | 1.0s |
| p4K | 25.1 | 314.9 | 24.4s |
| p32K | 20.1 | 244.9 | 149.1s |
| p64K | 18.4 | 189.4 | 366.0s |
| p128K | 14.5 | 133.2 | 1018.6s |
| p256K | 10.4 | 88.9 | 2814.1s |

> p256K elapsed: 2886s (~48 min).

### Cross-Model Comparison (Optimal Configs)

| Prompt | APEX I-Q | APEX I-B | 35B UD-Q8 | 27B Q8 | 27B Q6 | 27B Q4 |
|--------|---------|---------|--------|--------|--------|--------|
| p128 Gen | 84.1 | 78.2 | 56.7 | 13.8 | 18.9 | 26.5 |
| p4K Gen | 80.3 | 78.9 | 56.7 | 13.4 | 17.2 | 25.1 |
| p32K Gen | 62.3 | 65.1 | 50.1 | 12.5 | 15.8 | 20.1 |
| p64K Gen | 57.2 | 56.7 | 46.7 | 12.1 | 14.2 | 18.4 |
| p128K Gen | 47.0 | 45.3 | 38.0 | 10.0 | 11.2 | 14.5 |
| p256K Gen | 32.9† | 32.0† | 29.3† | 7.3 | 8.8 | 10.4 |
| p256K TTFT | 996s† | 1014s† | 999s† | 3022s | 3025s | 2814s |

> Configs: APEX I-Q/I-B = F16 KV (≤128K: UB=512, †256K: UB=256), 35B Q8 = F16 KV (≤128K: UB=512, †256K: UB=256), 27B Q8/Q6 = Q8_0 KV UB=512, 27B Q4 = Q8_0 KV UB=1024. Gen speeds include thinking tokens.

### Intelligence Test (35B MoE, MTP enabled)

8 questions covering math, logic, CS, and philosophy. Scored by keyword matching (max 10 per question, total 80). All models use F16 KV + UB=512 + MTP (`--spec-type draft-mtp --spec-draft-n-max 2`).

| Question | 35xq (I-Q) | 35xb (I-B) | 358 (Q8) |
|----------|-----------|-----------|----------|
| Gaussian sum (1+2+...+100) | 10/10 | 10/10 | 10/10 |
| Syllogism validity | 0/10 | 4/10 | 4/10 |
| Binary search complexity | 3/10 | 3/10 | 3/10 |
| River crossing puzzle | 10/10 | 10/10 | 10/10 |
| Quantum entanglement | 5/10 | **8/10** | 3/10 |
| Definite integral ∫₀¹x²dx | 3/10 | 3/10 | 3/10 |
| Liar paradox | 7/10 | 7/10 | **10/10** |
| LRU cache design | 10/10 | 10/10 | 10/10 |
| **Total** | **48/80** | **55/80** 🏆 | **53/80** |
| Avg Gen speed | 82.3 t/s | 81.7 t/s | 57.3 t/s |

> APEX I-Balanced scores highest (55/80) — imatrix calibration may better preserve reasoning patterns in MoE models. I-Quality is fastest but shows more reasoning errors (especially syllogism: 0/10). All three struggle with syllogism (keyword-based scoring may be strict). UD-Q8 scores 10/10 on liar paradox where APEX models get 7/10.

### Vision Test (35B MoE + mmproj, MTP enabled)

All three 35B MoE models share `mmproj-F16.gguf` (899 MB, qwen35moe architecture). Images sent as base64 via OpenAI chat completions API. All models use F16 KV + UB=512 + MTP.

| Image | Prompt tokens | Model | Gen (t/s) | MTP accept rate | Elapsed |
|-------|-------------|-------|-----------|----------------|---------|
| Baby sleeping (83 KB) | 939 | 35xq | **73.5** | 55.8% | 16.7s |
| | | 35xb | 69.6 | 52.4% | 14.6s |
| | | 358 | 51.2 | 50.9% | 18.3s |
| Outdoor photo (1.4 MB) | 2059 | 35xq | **69.8** | 52.3% | 22.3s |
| | | 35xb | 65.4 | 48.4% | 23.4s |
| | | 358 | 49.3 | 48.2% | 28.4s |
| Birthday photo (2.8 MB) | 4034 | 35xq | 70.5 | 53.9% | 35.2s |
| | | 35xb | **71.1** | 56.6% | 35.2s |
| | | 358 | 53.5 | 55.2% | 39.9s |

> Vision mode MTP accept rate (48–57%) is significantly lower than text mode (60–70%), as visual tokens are harder to predict. APEX I-Quality is ~39% faster than UD-Q8 on vision tasks. All three models accurately describe image contents.

---

## Optimization Parameters

### Key Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Service = server-level, INI = model-level | Clean separation; change model params without touching service file |
| Unified parallel=1, ctx=262144 | Simplifies config; one model per slot is sufficient for single-user workloads; dual-model via `--models-max 2`; 256K context covers all prompt lengths |
| Unified UB=256 | All models use ubatch=256 for stability. 278 UB=512 previously caused instability; unified to UB=256. UB≥1024 causes long-context prefill degradation; UB≥2048 Vulkan crash |
| `cache-ram = 16384/4096` (per-model in INI) | Prompt cache enabled per model: 278=16 GB (primary, long conversations), 358=4 GB (auxiliary, short tasks). Previously `--cache-ram 0` (disabled), then 32768 (32 GB, too large for dual-model GTT). 67K context uses ~15.7 GB, so 16 GB covers typical long conversations without exceeding GTT budget |
| `reasoning-budget = 16384` (per-model in INI) | Prevents thinking tokens from exhausting KV cache/VRAM while allowing longer reasoning chains. Previously 8192, doubled for better reasoning quality |
| No `reasoning-format = none` | This parameter puts thinking content into `delta.content` instead of `delta.reasoning_content`, causing SSE clients (like OpenClaw/QClaw) to mix thinking with the actual response, leading to duplicate output. Do not add it |
| All models: `parallel = 1`, `ctx-size = 262144` | 256K context per slot; single-user workload never needs concurrent slots; `parallel > 1` wastes KV cache memory |
| Service: `--models-max 2` | Dual-model resident: both 278 and 358 can be loaded simultaneously via router. Previously `models-max 1` (single-model rotation) used slot-save-path for checkpoint persistence; now dual-model with per-model cache-ram limits. Slot contention from earlier dual-model attempts was caused by the old non-router architecture; router mode provides independent slots per model |
| 27B Dense: `parallel = 1` only | `parallel ≥ 3` triggers Vulkan bug on 27B Dense models (see Known Issues) |
| `--spec-draft-n-max 2` | 3 is 20.6% slower than 2; 2 provides best speed/accuracy tradeoff with quantized KV cache |
| `-t 8` for all models | No difference vs `-t 16` with full GPU offload; t=8 runs cooler |
| No `--no-mmap` | No benefit; `--mmap` (default) + `--mlock` is the best combination |
| `-a Qwen3.6` | Sets model name in API responses; required by clients that validate the model field |
| `alias` short names | Convenient routing without symlinks; both alias and filename work |
| All models: F16 KV cache (default) | No explicit `cache-type-k`/`cache-type-v` in INI — llama-server defaults to F16. Q4_0 KV was previously tested on 278 (saves ~50% space, comparable prefill) but not currently used. Do not enable quantized KV on Vulkan backend (see Known Issues: MTP + Quantized KV) |
| `kv-unified = 1` (all models) | Unified KV cache for all slots; required for Vulkan backend slot-save/restore compatibility; also bypasses GGML_ASSERT crash path on Vulkan unified memory |
| System: CPU governor=performance | Reduces GPU command submission latency; improves gen speed and TTFT stability |
| System: `processor.max_cstate=1` | Prevents CPU deep C-states; reduces Vulkan command submission latency spikes |
| System: `vm.swappiness=1`, `vm.overcommit_memory=1` | Minimizes swap usage and prevents OOM killer false positives |
| No `--sleep-idle-seconds` | Loaded models stay resident; idle-unload → reload cycle causes memory spikes and OOM (see Known Issues) |

### Usage Constraints

| Constraint | Value | Reason |
|-----------|-------|--------|
| All models: concurrent slots | 1 (`parallel = 1`) | Single-user workload; `parallel > 1` wastes KV cache memory |
| All models: max context | 256K (`ctx-size = 262144`) | Unified context covers all prompt lengths |
| 27B Dense: `parallel` | 1 only | `parallel ≥ 3` triggers Vulkan bug (see Known Issues) |
| 35B MoE: UB constraints | UB=256 (current, stable across all context lengths) | Both 278 and 358 unified to UB=256 for stability; UB≥1024 degrades at ≥128K; UB≥2048 Vulkan crash |
| 27B Dense: UB constraints | F16 KV UB=256 (current, 278) | UB=512 previously caused instability; unified to UB=256; UB≥2048 Vulkan crash |
| Thinking mode | All models: enabled (`reasoning-budget=16384`) | Budget cap prevents runaway thinking; `reasoning=off` causes checkpoint restore bug (see Known Issues); clients disable thinking per-request via `chat_template_kwargs.enable_thinking: false` |
| No `reasoning-format=none` | Do not add | Causes thinking content to appear in `delta.content` instead of `delta.reasoning_content`, breaking SSE client parsing (see Known Issues) |
| Concurrency | 35B: up to 3, 27B Q8: up to 1, 27B Q6/Q4: up to 2 | Multi-slot supported; 278 parallel=1 to leave memory headroom when dual-model loaded |
| `cache-ram` | 278=`16384`, 358=`4096` (per-model in INI) | Prompt cache sized per model role: 278 (primary, 16 GB) covers ~67K context; 358 (auxiliary, 4 GB) for short tasks. Previously 32768 (32 GB) exceeded GTT budget under dual-model; `--cache-ram -1` caused unbounded growth (see Known Issues) |
| `kv-unified` | 1 (all models, set in INI) | Unified KV cache; required for Vulkan slot-save/restore; bypasses GGML_ASSERT crash on unified memory |
| `b` must divide by `ub` | `n_batch % n_ubatch == 0` | llama.cpp requirement |

### Parameter Separation Principle

| Scope | Where | Examples |
|-------|-------|---------|
| **Server-level** | `llm-router.service` ExecStart | `--host`, `--port`, `--api-key`, `--models-dir`, `--models-max`, `--models-preset`, `--timeout` |
| **Model-level** | `router-preset.ini` per-model section | `n-gpu-layers`, `ctx-size`, `ubatch-size`, `threads`, `alias`, `spec-type`, `mlock`, `numa`, ... |

> Model parameters are defined **only** in the INI — never duplicated in the service file.
>
> The full Preset INI and service config are included in each client section below (Hermes / QClaw).

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
- **Alias short names** (278/358) for convenient model selection

### Hardware

| Component | Specification |
|-----------|--------------|
| Machine | {your_machine} mini PC |
| APU | AMD Ryzen AI Max+ 395 (16C, SMT disabled) |
| Memory | 128 GB LPDDR5X (256-bit, unified memory) |
| Storage | 1 TB NVMe SSD |
| iGPU | Radeon 8060S (RDNA 3.5, 40 CU, 2040 MHz) |
| GTT (GPU-accessible RAM) | 120 GB (kernel param `amdgpu.gttsize=122880`) |

**Memory bandwidth:** 256-bit × 8000 MT/s ÷ 8 = **256 GB/s** theoretical, ~200 GB/s practical. Dense models are memory-bandwidth bound.

### BIOS Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| SMT (Simultaneous Multithreading) | **Disabled** | LLM inference is memory-bandwidth bound; disabling SMT reduces cache contention and improves KV cache hit rates |
| GFX Workstation Support | **Disabled** | Not needed for headless inference; frees resources |
| iGPU Mem Bar Configuration | **ResizableBAR** | Allows GPU to access full system memory for large model weights |
| UMA Version | **Non-Legacy** | Required for ResizableBAR and large unified memory allocation |
| Dedicated Graphics Memory | **0.5G** | Minimum allocation; system memory handles model weights via GTT |

> **Why disable SMT?** LLM inference on unified memory is bandwidth-bound (256 GB/s). SMT adds thread contention on shared L3 cache without improving bandwidth utilization. Real-world testing shows improved cache hit rates and more stable latency with SMT off.

### GRUB Kernel Parameters

**File:** `/etc/default/grub`

```bash
GRUB_CMDLINE_LINUX_DEFAULT="amd_iommu=off amdgpu.gttsize=122880 processor.max_cstate=1"
```

- `amd_iommu=off` — disables IOMMU, reduces memory translation overhead for GPU DMA
- `amdgpu.gttsize=122880` — sets GPU-accessible system memory (GTT) to 120 GB, allowing the iGPU to access nearly all 128 GB RAM for model weights
- `processor.max_cstate=1` — prevents CPU from entering deep C-states, reducing latency for Vulkan GPU command submission and KV cache operations

**Apply:** `sudo update-grub && sudo reboot`

### Software

| Component | Version / Details |
|-----------|-------------------|
| Inference OS | Ubuntu 26.04 LTS |
| Cloud OS | Ubuntu 24.04.4 LTS |
| llama.cpp | b9592 (commit ac4cddeb0, Vulkan backend) |
| Build options | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` |

> ⚠️ **Version upgraded from b9315 to b9592 (2026-06-11).** Commit `6c4cbdc70` ("server: MTP layer kv-cache should respect draft type ctk") is still present in b9592, but the current deployment uses default F16 KV cache (no explicit `cache-type-k`/`cache-type-v` in INI), so this bug **does not trigger**. It would only manifest if quantized KV (e.g. `q8_0`, `q4_0`) is re-enabled. Do not enable quantized KV on the Vulkan backend until upstream fixes this.
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
| Router preset (all models) | `$HOME/model/router-preset.ini` |

### Model Inventory

Router Mode serves all models from `$HOME/model/`. Dual-model mode (`--models-max 2`): both 278 and 358 can be loaded simultaneously via router with independent slots. Each model has an **alias** for short-name routing.

**Model sources (HuggingFace):**

| Source | Short | Models | Description |
|--------|-------|--------|-------------|
| [unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | **UD-35B** | 358 | Unsloth Dynamic quant for 35B MoE |
| [mudler/Qwen3.6-35B-A3B-APEX-MTP-GGUF](https://huggingface.co/mudler/Qwen3.6-35B-A3B-APEX-MTP-GGUF) | **APEX-35B** | 35xb, 35xq | APEX adaptive-precision quant for 35B MoE |
| [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) | **UD-27B** | 278, 276, 274 | Unsloth Dynamic quant for 27B Dense |

| Alias | File | Source | Quant | Arch | Size | Active Params | Role |
|-------|------|--------|-------|------|------|---------------|------|
| **35xb** | `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced.gguf` | APEX-35B | APEX mixed | **MoE** | ~24 GB | 3B | Deleted (file removed 2026-06-12) |
| **358** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | UD-35B | UD-Q8_K_XL | **MoE** | ~37 GB | 3B | Auxiliary (Hermes auxiliary tasks, vision) |
| **35xq** | `Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf` | APEX-35B | APEX mixed | **MoE** | ~22 GB | 3B | Deleted (file removed) |
| **278** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | UD-27B | UD-Q8_K_XL | Dense | ~33 GB | 27B | Primary (Hermes default + fallback) |
| **276** | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | UD-27B | UD-Q6_K_XL | Dense | ~25 GB | 27B | Deleted (file removed) |
| **274** | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | UD-27B | UD-Q4_K_XL | Dense | ~17 GB | 27B | Deleted (file removed) |

> **Alias naming convention:** `35b` is reserved for the Qwen3.6-35B-A3B architecture family. APEX variants use `35xq` (I-Quality) and `35xb` (I-Balanced). UD models use 3 digits = model size + quant level (e.g. `358` = 35B Q8, `276` = 27B Q6). Both alias and full filename work in API requests.
>
> **Deployment modes:**
> - **Dual-model resident**: `models-max 2` → both 278 and 358 loaded simultaneously via router (independent slots, no contention). Per-model `cache-ram` limits prevent GTT budget overflow. GTT 120GB + mlock=1. No `--sleep-idle-seconds`.
>
> **Deleted models:** 35xb (24 GB, removed 2026-06-12), 35xq (21.9 GB), 276 (25 GB), 274 (17 GB) removed to reclaim disk space. Benchmark data and test scripts preserved in git for reference.

### 1. Cloud Nginx Configuration

**File:** `/etc/nginx/sites-enabled/default` (LLM-relevant sections)

#### nginx.conf key settings

```nginx
server_tokens off;          # Hide Nginx version
gzip off;                   # Global gzip off; per-location control

# Rate limiting (in http block)
limit_req_zone $binary_remote_addr zone=api:10m rate=60r/m;
```

#### LLM-related locations

```nginx
server {
    listen 443 ssl default_server;
    client_max_body_size 64m;   # Support large prompt requests
    server_tokens off;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # /v1/props — Hermes capability probe; not implemented by llama-server
    location = /v1/props {
        access_log off;
        default_type application/json;
        return 200 '{}';
    }

    # LLM Inference API (OpenAI-compatible) — SSH tunnel port 8080 → llama-server
    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        limit_req zone=api burst=20 nodelay;

        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Long timeout (Nginx ≥ llama-server --timeout 3600)
        proxy_read_timeout 3600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;

        # SSE streaming
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        gzip off;              # SSE requires gzip off
    }

    # Health check
    location /health {
        limit_req zone=api burst=20 nodelay;
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**Configuration notes:**
- **`/v1/`** — OpenAI-compatible API proxy to `127.0.0.1:8080` (SSH reverse tunnel → inference server)
- `/v1/props` returns `{}` to avoid 404 noise from Hermes capability probes
- `limit_req_zone 60r/m burst=20` — all locations share the same rate limiter
- `server_tokens off` — double-enforced (nginx.conf + server block)
- `client_max_body_size 64m` — supports 100K+ token long prompts
- Global `gzip off`; `/v1/` explicitly `gzip off` (SSE requirement)
- All timeouts aligned: Nginx 3600s ↔ llama-server 3600s ↔ Hermes 3600s

**Apply:** `sudo nginx -t && sudo systemctl reload nginx`

**Link latency reference** (WSL → Cloud Nginx → SSH tunnel → Inference box):

| Endpoint | TTFB | Notes |
|----------|------|-------|
| `/v1/props` | ~165ms | Nginx returns `{}` directly |
| `/v1/models` | ~390-480ms | Proxied to llama-server |
| `/v1/chat/completions` (short) | ~1.3s | Includes inference time |

> Pure link overhead (DNS + TLS + SSH tunnel): ~400-500ms. This is inherent to the SSH reverse tunnel architecture.

### 2. Cloud SSH Server

**File:** `/etc/ssh/sshd_config`

```sshd_config
AllowTcpForwarding yes
ClientAliveInterval 60
ClientAliveCountMax 3
# GatewayPorts no   (default — keep tunnel on 127.0.0.1 only)

# Security: key-only auth (disable password login)
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

> ⚠️ **Important:** Ubuntu's `/etc/ssh/sshd_config.d/` directory contains drop-in files (e.g., `50-cloud-init.conf`) that **override** the main config. You must also check and edit files in that directory, or `PasswordAuthentication no` may not take effect. Verify with: `sudo sshd -T | grep passwordauthentication`

**Apply:** `sudo systemctl restart ssh`

**Verify:** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|passwordauthentication|pubkeyauthentication"`

### 3. SSH Reverse Tunnel (systemd)

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
    {your_server_user}@{your_server_ip}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

**Tunnel port:** `-R 8080:127.0.0.1:12345` (API only)

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
ssh -R 8080:127.0.0.1:12345 {your_server_user}@{your_server_ip} -N
# On cloud, verify:
curl http://127.0.0.1:8080/v1/models
```

**SSH key setup (passwordless):**
```bash
ssh-keygen -t ed25519 -C "llm-tunnel@{your_hostname}"
ssh-copy-id {your_server_user}@{your_server_ip}
```

### 4. Swap Configuration (Ubuntu)

```bash
# Check current swap
swapon --show

# Create 32 GB swap file
sudo fallocate -l 32G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

> 32 GB swap provides safety margin for dual-model cold-load memory spikes. With `--sleep-idle-seconds` removed and models resident, actual swap usage should be minimal (~17 MB observed).

### 5. GPU Temperature Monitoring

The FEVM FAEX1 mini PC motherboard (ITE 0x5571 chip) has no upstream Linux `lm-sensors` driver, and the AMD Ryzen AI Max+ 395 `k10temp` module is not recognized on kernel 7.0.0-15. However, GPU temperature is available via the `amdgpu` hwmon subsystem.

**Monitoring script:** `~/scripts/gpu-temp-log.sh`

```bash
#!/bin/bash
# GPU temperature logger — reads amdgpu hwmon
# Runs every 5 minutes via systemd user timer

LOGDIR="$HOME/logs"
mkdir -p "$LOGDIR"

ts=$(date '+%Y-%m-%d %H:%M:%S')

gpu_temp=$(cat /sys/class/drm/card0/device/hwmon/hwmon*/temp1_input 2>/dev/null)
gpu_temp_c=$((gpu_temp / 1000))

gpu_junc=$(cat /sys/class/drm/card0/device/hwmon/hwmon*/temp2_input 2>/dev/null)
gpu_junc_c=$((gpu_junc / 1000))

gpu_mem=$(cat /sys/class/drm/card0/device/hwmon/hwmon*/temp3_input 2>/dev/null)
gpu_mem_c=$((gpu_mem / 1000))

gpu_busy=$(cat /sys/class/drm/card0/device/gpu_busy_percent 2>/dev/null)

gpu_pwr_uw=$(cat /sys/class/drm/card0/device/hwmon/hwmon*/power1_input 2>/dev/null)
gpu_pwr_w=$((gpu_pwr_uw / 1000000))

mem_avail=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
mem_total=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
mem_used_gb=$(awk "BEGIN {printf \"%.1f\", ($mem_total - $mem_avail) / 1048576}")
mem_total_gb=$(awk "BEGIN {printf \"%.1f\", $mem_total / 1048576}")

junc_str="${gpu_junc_c}°C"
mem_str="${gpu_mem_c}°C"
[ "$gpu_junc" = "" ] && junc_str="N/A"
[ "$gpu_mem" = "" ] && mem_str="N/A"

echo "$ts | GPU ${gpu_temp_c}°C (junc ${junc_str}, mem ${mem_str}) | ${gpu_busy}% busy | ${gpu_pwr_w}W | RAM ${mem_used_gb}/${mem_total_gb}GB"
```

**systemd user timer:** `~/.config/systemd/user/gpu-temp-log.timer`

```ini
[Unit]
Description=GPU Temperature Logger Timer

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

**systemd user service:** `~/.config/systemd/user/gpu-temp-log.service`

```ini
[Unit]
Description=GPU Temperature Logger

[Service]
Type=oneshot
ExecStart=/bin/bash -c '/home/$USER/scripts/gpu-temp-log.sh >> /home/$USER/logs/gpu-temp.log 2>&1'
```

**Setup:**

```bash
mkdir -p ~/scripts ~/logs
# Save script to ~/scripts/gpu-temp-log.sh
chmod +x ~/scripts/gpu-temp-log.sh
# Save service + timer units to ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gpu-temp-log.timer
```

**Log format:** `timestamp | GPU temp (junction, memory) | GPU busy % | Power W | RAM used/total GB`

**Sample output:**
```
2026-06-03 13:25:28 | GPU 82°C (junc N/A, mem N/A) | 100% busy | 108W | RAM 106.0/124.9GB
```

> **Note:** Junction and memory temperatures are not available on this APU (temp2_input/temp3_input not exposed by the amdgpu driver). The GPU edge temperature (`temp1_input`) is the primary monitoring metric. Observed range under full inference load: 78–82°C (TjMax 100°C).

### 6. Preset INI (Per-Model Parameters)

**File:** `~/model/router-preset.ini`

```ini

[Qwen3.6-27B-UD-Q8_K_XL]                    # alias: 278 — primary (Hermes default + fallback)
n-gpu-layers = 99
flash-attn = 1
kv-unified = 1
parallel = 1
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
spec-type = draft-mtp
spec-draft-n-max = 2
cache-ram = 16384
slot-save-path = /home/zxw/kv-checkpoints/278/
mlock = 1
numa = distribute
reasoning-budget = 16384
threads = 8
temp = 0.6
top-p = 0.95
top-k = 20
presence-penalty = 0.0
min-p = 0.0
slot-prompt-similarity = 0.8
alias = 278

[Qwen3.6-35B-A3B-UD-Q8_K_XL]                # alias: 358 — auxiliary (Hermes auxiliary tasks, vision)
n-gpu-layers = 99
flash-attn = 1
kv-unified = 1
parallel = 1
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
mmproj = /home/zxw/mmproj/mmproj-F16.gguf
image-min-tokens = 2048
spec-type = draft-mtp
spec-draft-n-max = 2
cache-ram = 4096
slot-save-path = /home/zxw/kv-checkpoints/358/
mlock = 1
numa = distribute
reasoning-budget = 16384
threads = 8
temp = 0.6
top-p = 0.95
top-k = 20
presence-penalty = 0.0
min-p = 0.0
slot-prompt-similarity = 0.8
alias = 358


```

**To change model parameters:** edit the INI file → restart llama-server (via `systemctl --user restart llm-router` or manual restart)

### 7. Inference Service (systemd)

**File:** `~/.config/systemd/user/llm-router.service` (user-level, no sudo needed)

```ini
[Unit]
Description=llama.cpp Router Server
After=network.target

[Service]
Type=simple
ExecStart=/home/$USER/scripts/llama-router.sh
ExecStartPost=-/bin/bash -c 'nohup /home/$USER/scripts/slot-checkpoint.sh restore >> /home/$USER/logs/llama/checkpoint.log 2>&1 &'
Restart=on-failure
RestartSec=10
TimeoutStartSec=300
TimeoutStopSec=35
KillMode=process
LimitMEMLOCK=infinity

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable llama-router
systemctl --user start llama-router
loginctl enable-linger   # survive logout
```

> The service uses a wrapper script (`llama-router.sh`) that handles SIGTERM cleanup (saves KV checkpoint before exit) and logs output. `ExecStartPost` automatically restores the last checkpoint on startup. The wrapper runs `llama-server` with `--models-max 2` (both models can be loaded) and `--models-preset` (per-model params from INI). Model parameters (cache-ram, ubatch, etc.) are defined in the preset INI, not in the service file. GTT 120GB + mlock=1 ensures model weights stay in physical memory. `LimitMEMLOCK=infinity` allows mlock of all model weights. `TimeoutStartSec=300` prevents systemd from killing the service during long model loads.

### 8. Model Switching

Clients specify the `model` field in API requests. Both **alias short names** and **full filenames** work. Router switches automatically (LRU, 8–17 seconds cold load):

```bash
# Using alias (recommended)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "278", ...}'   # primary model (Hermes default)

# Using full filename (also works)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "Qwen3.6-35B-A3B-UD-Q8_K_XL", ...}'

# Switch to auxiliary model (for vision, compression, etc.)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "358", ...}'
```

### Client Integration

#### Hermes Agent

[Hermes](https://github.com/nicobailon/hermes-agent) v0.15.1 — terminal AI agent with TUI, oneshot mode, multi-platform Gateway, MCP, Skills, and cron scheduling.

**Install path:** `~/.hermes/` on WSL Ubuntu 26.04

**Config file:** `~/.hermes/config.yaml`

```yaml
providers:
  custom:local-llm:                                    # ⚠️ must include "custom:" prefix to match model.provider
    name: "Local LLM (Strix Halo)"
    base_url: "https://{your_domain}/v1"
    key_env: "DASHENZHIYAN_API_KEY"
    extra_body:
      chat_template_kwargs:
        enable_thinking: true       # enables thinking mode
    models:
      "278":
        context_length: 262144
        max_output_tokens: 32768
        supports_vision: false   # 27B Dense has no mmproj
      "358":
        context_length: 262144
        max_output_tokens: 32768
        supports_vision: true    # 35B MoE with mmproj, handles vision tasks
    request_timeout_seconds: 3600  # API request timeout (aligned with llama-server --timeout)
    stale_timeout_seconds: 3600   # stream stale detection (must match request_timeout for long contexts)

model:
  default: "278"                   # primary model: 278 (27B Dense, highest quality, ~13 t/s)
  provider: "custom:local-llm"
  base_url: "https://{your_domain}/v1"
  extra_body:
    chat_template_kwargs:
      enable_thinking: true
max_tokens: 32768                 # must ≥ reasoning-budget + expected output

fallback_model:
  provider: custom:local-llm
  model: '278'                     # same as default; 358 available for manual switch

agent:
  gateway_timeout: 3600           # gateway-level timeout (aligned with all other timeouts)

streaming:
  enabled: true                  # gateway bot streaming (editMessage)

compression:
  enabled: true
  threshold: 0.80                # trigger compression at 80% context
  target_ratio: 0.30             # keep 30% of threshold as recent tail
  protect_last_n: 20             # never compress the most recent 20 messages

auxiliary:                         # all auxiliary tasks routed to 358 (vision-capable MoE, ~50 t/s)
                                  # 278 = primary model (main conversations, highest quality)
                                  # 358 = auxiliary model (compression, vision, etc.)
                                  # title_generation uses 278 to avoid model switching churn
  vision:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"   # MUST be explicit - empty string causes RuntimeError
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  web_extract:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  compression:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  skills_hub:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  approval:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  mcp:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  title_generation:
    provider: custom:local-llm
    model: '278'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  triage_specifier:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  kanban_decomposer:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  profile_describer:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  curator:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false

approvals:
  mode: auto                        # routine ops pass; destructive actions require confirmation
  timeout: 3600                     # CLI approval timeout
  gateway_timeout: 3600             # Gateway (QQ Bot) approval timeout; defaults to 300s if unset

**Configuration notes:**
- `provider: "custom:local-llm"` — uses named providers section ("custom" direct-alias ignores `extra_body`)
- ⚠️ **providers key must include `custom:` prefix** — i.e. `custom:local-llm`, not `local-llm`. If the key doesn't match `model.provider`, Hermes' `get_provider_request_timeout()` returns `None` → falls back to hardcoded `HERMES_STREAM_READ_TIMEOUT = 120s`, causing long-context requests to time out. This was the root cause of a cascading timeout incident (see Known Issues)
- `key_env: "DASHENZHIYAN_API_KEY"` — set in `~/.hermes/.env`
- `supports_vision: false` on 278 (27B Dense, no mmproj); `supports_vision: true` on 358 (35B MoE, has mmproj)
- `max_tokens: 32768` — must be ≥ reasoning-budget (16384) + expected output; 8192 is too small
- `chat_template_kwargs: enable_thinking: true` — enables thinking mode; omit or set `false` to disable
- `context_length` is per-slot (ctx-size ÷ parallel), not total ctx-size
- `stale_timeout_seconds: 3600` — must align with `request_timeout_seconds` for long-context prefill (>1000s)
- `gateway_timeout: 3600` — gateway-level timeout aligned with all other timeouts
- `auxiliary` — all 11 tasks routed to 358 (vision-capable MoE, ~50 t/s); `enable_thinking: false` to reduce latency; `timeout: 3600` aligned with full-chain timeout
- `auxiliary.vision.base_url` — ⚠️ **MUST be explicit** set to `https://{your_domain}/v1`. Empty string causes `resolve_vision_provider_client()` to skip the explicit branch, fall through to `_get_cached_client(is_vision=True)` → returns None → RuntimeError. Non-vision auxiliary tasks are safe with empty string (different code path). See Known Issues.
- `approvals.mode: auto` — routine operations (file read, tool calls) pass automatically; only destructive actions (file deletion, dangerous commands) require manual confirmation. Use `manual` to require approval for everything (tedious for QQ Bot).
- `approvals.timeout: 3600` — CLI approval max wait before auto-reject.
- `approvals.gateway_timeout: 3600` — ⚠️ **Gateway (QQ Bot) approval timeout**. This field is separate from `timeout`; if unset, defaults to 300s (5 minutes). Users on messaging platforms often need more time to respond. Must be explicitly set to match the full-chain timeout.

**Environment variable overrides** (`~/.hermes/.env`):

```bash
# Override Hermes hardcoded defaults — prevent long-context timeout at 120s/180s
HERMES_STREAM_READ_TIMEOUT=3600
HERMES_STREAM_STALE_TIMEOUT=7200


```

**Usage:**
```bash
wsl                                    # enter WSL
hermes                                 # TUI mode (interactive)
hermes -z 'quick question'             # oneshot mode
hermes -z 'question' --model 358       # oneshot with specific model
```

**TUI commands:** `/model 358` switch model, `/skills` list skills, `/help` all commands, `Ctrl+C` interrupt, `Ctrl+D` or `/exit` quit.

#### QClaw

QClaw (OpenClaw) — personal AI assistant with multi-channel support (WeChat, QQ, webchat).

**Provider config** (`~/.qclaw/openclaw.json`):
- `qclaw` provider → `http://127.0.0.1:19000/proxy/llm` (cloud proxy with model routing)
- Single model `modelroute`: reasoning enabled, input supports text + image
- Default model: `qclaw/pool-glm-5.1` (cloud proxy, does not directly hit inference server)
- Channels: `wechat-access` (QQ), `openclaw-weixin` (WeChat local)
- Plugins: `lossless-claw`, `browser`, `wechat-access`, `openclaw-weixin`, `qclaw-plugin`, `qclaw-embedding`, `memory-core`
- Context engine: `lossless-claw` (LCM-based lossless context management)

**Streaming:** WeChat/QQ/WeCom: blockStreaming; Telegram/Discord/Slack: edit-message streaming

### Verification Checklist

- [ ] Cloud Nginx config updated (with `/v1/` and `/health` endpoints)
- [ ] Cloud SSL certificates configured
- [ ] Cloud `sshd_config` allows TCP forwarding and keepalive
- [ ] Inference box has SSH key for passwordless login to cloud
- [ ] `llm-tunnel.service` created and **active**
- [ ] Cloud: `ss -tlnp | grep 8080` shows tunnel listening
- [ ] `llm-router.service` created and **active** (server-level params only)
- [ ] `~/model/router-preset.ini` configured with per-model params + aliases (278/358 only)
- [ ] Cloud: `curl http://127.0.0.1:8080/v1/models` returns models with aliases
- [ ] Dual-model mode: both 278 and 358 loaded with independent slots
- [ ] No `--sleep-idle-seconds` in service config (prevents OOM from reload cycles)
- [ ] External: `curl https://{your_domain}/health` returns `OK`
- [ ] GPU temperature monitoring: `systemctl --user status gpu-temp-log.timer` active
- [ ] GPU temp log: `cat ~/logs/gpu-temp.log` shows entries every 5 minutes
- [ ] Alias routing: `curl -d '{"model":"358",...}'`、`curl -d '{"model":"278",...}'` both work

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

## Known Issues

### `reasoning-format=none` Causes Duplicate Output in SSE Clients

**Status:** Fixed — removed from `router-preset.ini`

**Affected clients:** OpenClaw/QClaw and any SSE client using `@mariozechner/pi-ai` OpenAI completions parser.

**Symptom:** Assistant responses contain duplicated content — the thinking process followed by the actual answer appear mixed together, then repeated in the next turn.

**Root cause:** `reasoning-format=none` tells llama-server to put thinking content into `delta.content` (instead of the standard `delta.reasoning_content` field). The OpenAI completions SSE parser treats all `delta.content` as regular text, creating a single text block that contains both thinking and the actual response. When stored in conversation history, the next turn sees the thinking content, causing the model to repeat.

**Verification:** Without `reasoning-format=none`, SSE chunks correctly separate:
- Thinking → `delta.reasoning_content` → parser creates independent `thinking` block
- Response → `delta.content` → parser creates `text` block

**Fix:** Remove `reasoning-format = none` from all model sections in `router-preset.ini`. Thinking will use the standard `reasoning_content` field.

---

### Vulkan + parallel=3 + MTP Crash on 27B Dense Models

**Status:** Open — waiting for upstream fix (PR [#22453](https://github.com/ggml-org/llama.cpp/pull/22453))

**Affected models:** 27B Dense series (aliases `278`/`276`/`274`). 35B MoE models (aliases `358`/`35xb`/`35xq`) are **not** affected.

**Symptom:** `llama-server` aborts with `GGML_ASSERT` failure when processing any request on 27B Dense models with `parallel ≥ 3` and MTP enabled.

**Reproduction:**
```ini
# router-preset.ini — triggers the crash
[Qwen3.6-27B-UD-Q8_K_XL]
parallel = 3
spec-type = draft-mtp
spec-draft-n-max = 3
ctx-size = 786432
# ... other params
```

**Crash output:**
```
/home/$USER/llama/llama.cpp/ggml/src/ggml-backend.cpp:348: GGML_ASSERT(tensor->data != NULL && "tensor not allocated") failed
```

**Root cause:** Vulkan backend uses device-only (unified) memory buffers. Per-slot KV cache tensors have `tensor->data == NULL` on the host side (data lives on GPU). `ggml_backend_tensor_get()` and related functions unconditionally assert `tensor->data != NULL`, which fails when the prompt cache system attempts to save/restore slot state (including MTP draft context). The crash occurs in two paths:

1. **Direct path:** `ggml_backend_tensor_get()` — `ggml-backend.cpp:348`
2. **MTP draft path:** `common_prompt_checkpoint::update_dft()` → `llama_context::state_seq_get_data()` → `llama_io_write_host` — `common.cpp:2082`

**Affected code** (`ggml/src/ggml-backend.cpp`, 11 occurrences):
```cpp
// Line 348 — one of 11 identical assertions that fail on Vulkan unified memory
GGML_ASSERT(tensor->data != NULL && "tensor not allocated");
```

**Workaround attempted:** `kv-unified = 1` (currently enabled) bypasses crash path #1 but **not** crash path #2 (MTP draft checkpoint). Not viable for `parallel ≥ 3`.

**Current mitigation:** All 27B Dense models set to `parallel = 1` (single-user scenario, no concurrency needed). This avoids the crash at the cost of no concurrent slots.

**Upstream tracking:**
- Issue [#19839](https://github.com/ggml-org/llama.cpp/issues/19839) — original bug report
- PR [#22453](https://github.com/ggml-org/llama.cpp/pull/22453) — proposed fix (add NULL check before assert, delegate to backend `get_tensor`); closed but not merged
- As of b9315 (commit `314e72934`), all 11 assert locations remain unchanged in `ggml-backend.cpp`

---

### OOM Kill with Dual-Model + `--sleep-idle-seconds`

**Status:** Resolved — removed `--sleep-idle-seconds` from service config

**Affected scenario:** Main model (27B Q8) + auxiliary model in dual-model resident mode (`models-max 2`), with `--sleep-idle-seconds` configured. **This scenario is obsolete — current deployment uses dual-model resident mode (`models-max 2`) without `--sleep-idle-seconds`.**

**Symptom:** Linux OOM killer terminates `llama-server` after hours of operation.

**Root cause chain:**
1. `--sleep-idle-seconds 600` unloads the 35xq model after 10 minutes of inactivity, releasing memory
2. Next request for 35xq triggers a cold reload → model weights read from disk + `mlock` into RAM
3. During cold reload, the already-loaded model and the loading model coexist in memory
4. 278 previously ran with `parallel = 2` (now fixed to `parallel = 1`) → large KV cache pre-allocation + prompt cache accumulation
5. Cold reload memory spike exceeds 128 GB RAM + 8 GB swap → OOM Kill

**Key insight:** Without `--sleep-idle-seconds`, loaded models stay resident. Since only 278 and 358 are actively requested by clients, both remain loaded under `models-max 2`. There is no LRU eviction because no third model is requested. The idle-unload/reload cycle is the root cause of the OOM.

**Resolution:**
- Removed `--sleep-idle-seconds` from service config
- All models use `parallel = 1`, `ctx-size = 262144` to leave memory headroom for dual-model co-residency
- Memory headroom: 80.6 GB used / 131 GB total, ~44 GB available, swap ~17 MB

**Warning:** Do **not** re-add `--sleep-idle-seconds`. If a third model is requested (e.g., 358), LRU eviction will unload one of the two loaded models. This is expected behavior — the freed slot will be used for the requested model. If both 278 and 35xq must remain loaded, ensure no client requests a third model, or use a dedicated directory with only 2 models.

### `reasoning=off` Causes Catastrophic Checkpoint Restore Slowdown on APEX I-Quality

**Status:** Fixed — removed `reasoning = off` and `reasoning-budget = 0` from 35xq preset, replaced with `reasoning-budget = 8192`

**Affected model:** 35B-A3B APEX I-Quality (alias `35xq`, deleted) only. All other models (358/35xb/278) are unaffected.

**Symptom:** After the first request to 35xq, subsequent requests take 43–75 seconds instead of <0.5 seconds. The server appears frozen — no output for tens of seconds, then response arrives at ~1 t/s.

**Root cause:** `reasoning = off` creates an attention mask mismatch between the checkpoint (saved with default reasoning-enabled state) and the model's runtime configuration. When llama-server attempts to restore a prompt cache checkpoint, it detects the mismatch and falls back to a slow path — re-prefilling all tokens from the checkpoint instead of loading the KV cache snapshot directly.

**Evidence:**

| Configuration | Prefill speed | Checkpoint restore |
|--------------|-------------|-------------------|
| `reasoning=off` (broken) | 0.37–0.95 t/s | 43–75s ❌ |
| `reasoning-budget=8192` (fixed) | 118–129 t/s | <0.1s ✅ |

Other MoE models (358, 35xb) with reasoning enabled have no checkpoint issues. Only the combination of `reasoning=off` + APEX I-Quality triggers the bug.

**Fix:** Remove `reasoning = off` and `reasoning-budget = 0` from the 35xq preset section. Use `reasoning-budget = 8192` (same as other models). If thinking output is not desired, disable it per-request via `chat_template_kwargs: { enable_thinking: false }` in the API request body.

**Warning:** Do **not** re-add `reasoning = off` to any model preset. This is the third reasoning-related bug discovered (after `reasoning-format=none` causing duplicate output, and `reasoning=off` causing checkpoint restore failure). The safe approach is to always keep reasoning enabled at the server level and control it per-request.

---

### MTP + Quantized KV Cache Causes Vulkan DeviceLost (b9318+)

**Status:** Open — version locked at b9315; awaiting upstream fix

**Affected models:** All models with MTP speculative decoding + quantized KV cache (`cache-type-k` / `cache-type-v`). Current deployment uses default F16 KV (no explicit `cache-type-k`/`cache-type-v` in INI), so this issue is **not currently triggered**. It would only manifest if quantized KV (e.g. `q8_0`, `q4_0`) were re-enabled on any model. 35B MoE models (358/35xb) have always used F16 KV and are not affected.

**Symptom:** `vk::DeviceLostError` (`vk::Queue::submit: ErrorDeviceLost`) during MTP draft decode, causing llama-server slot process crash. Client sees HTTP 500 / "Failed to read connection".

**Reproduction:**
```ini
# router-preset.ini — triggers the crash on b9318+
[Qwen3.6-27B-UD-Q4_K_XL]
parallel = 1
ctx-size = 262144
cache-type-k = q8_0       # quantized KV
spec-type = draft-mtp      # MTP enabled
spec-draft-n-max = 3
# ...
```

**Culprit commit:** `6c4cbdc70` — "server: MTP layer kv-cache should respect draft type ctk" (#23646). Adds 4 lines in `tools/server/server-context.cpp` that set `type_k` and `type_v` for MTP context. When MTP context uses quantized KV formats (e.g., `q8_0`), the Vulkan backend triggers `vk::DeviceLostError` at long context lengths.

**Bisection:** b9297 GOOD → b9315 GOOD → b9318 BAD. 6 rounds.

**Stress test results (b9465, 278 model):**

| Config | p32K | p64K | p128K | p256K |
|--------|------|------|-------|-------|
| MTP + Q8_0 KV | ✅ | ❌ DeviceLost | ❌ DeviceLost | — |
| No MTP | — | ✅ | ✅ | ✅ |
| b9315 + MTP | ✅ | ✅ | ✅ | ✅ (128K tokens verified) |

**Root cause:** MTP draft KV cache with quantized types triggers a Vulkan driver bug in radv/amdgpu. Long-context scenarios (≥64K tokens) with high-frequency GPU submissions cause device context loss. The bug is in the interaction between quantized MTP KV cache and the Vulkan memory management — not in the commit's logic itself, but the commit exposes the latent bug.

**Workaround:** Upgraded to b9592 (F16 KV does not trigger this bug). Do **not** enable quantized KV types until upstream addresses the Vulkan + quantized KV cache interaction.

**Upstream tracking:** No issue filed yet. The regression is specific to Vulkan backend + MTP + quantized KV; other backends (CPU/CUDA/Metal) are unaffected.

---

### `--cache-ram -1` Causes VRAM Contention and 35B Cold-Load Stall

**Status:** Mitigated — prompt cache now per-model in INI (278 `cache-ram = 16384`, 358 `cache-ram = 4096`), no longer in service config. Dual-model mode with per-model limits prevents unbounded growth.

**Affected scenario:** Dual-model resident mode (`models-max 2`) with one model already loaded and serving long-context requests. **Mitigated by per-model `cache-ram` limits in INI.**

**Symptom:** When the 27B model runs first and accumulates a large prompt cache (~12.4 GB for 131K tokens), a subsequent request to a 35B model triggers a cold load that stalls for 20+ minutes in the "fitting params to device memory" phase. The server appears frozen.

**Root cause chain:**
1. `--cache-ram -1` allows the 27B's prompt cache to grow without bound (up to ~30 checkpoints × ~400 MB each on Vulkan unified memory)
2. After serving long-context requests, the 27B's prompt cache consumes ~12+ GB of memory, leaving insufficient headroom
3. When the 35B is requested, llama-server must fit its ~22–37 GB model weights into the remaining memory
4. With most free memory already consumed by the 27B's prompt cache, the 35B loading process enters a tight allocation-retry loop during "fitting params to device memory"
5. This loop can last 20–30 minutes before eventually succeeding or being killed

**Evidence (from logs):**
- 35B cold load during normal conditions (both models not yet loaded): ~14 seconds
- 35B cold load with 27B already occupying memory via `--cache-ram -1`: 20–28 minutes
- System memory at saturation: 96+ GiB used out of 124 GiB, with buffer/cache inflating apparent usage
- After removing `-1`: dual-model loading complete in ~14 seconds, swap usage dropped from 10 GiB to 256 KiB

**Fix:**
- Prompt cache moved from service-level `--cache-ram` to per-model in INI: 278 `cache-ram = 16384`, 358 `cache-ram = 4096`
- Dual-model mode with per-model `cache-ram` limits (`--models-max 2`), both models in memory with independent slots
- Combined with per-model `--slot-save-path` KV checkpoint save/restore in INI, model switch latency is 30–60 seconds
- GTT 120GB + mlock=1 ensures model weights stay in physical memory
- **Do not** use `--cache-ram -1` in dual-model resident mode (`models-max 2`)

**Warning:** `--cache-ram -1` is only safe in single-model rotation mode with controlled workloads. In dual-model resident mode (`models-max 2`), with only 128 GB unified memory and two models totaling 41–59 GB, unlimited prompt cache from one model will starve the other on cold load. Current deployment uses `cache-ram = 16384/4096` (per model in INI) for stability.

---

### Hermes Vision `base_url: ''` Causes RuntimeError

**Status:** Resolved — set `auxiliary.vision.base_url` to `https://{your_domain}/v1`

**Affected scenario:** Hermes config with `auxiliary.vision.base_url` as empty string (`''`).

**Symptom:** Vision requests fail with `RuntimeError: No LLM provider configured for task=vision`.

**Root cause chain:**
1. `resolve_vision_provider_client()` checks `base_url` first — empty string is falsy → skips explicit branch
2. `requested="custom:local-llm"` ≠ `"auto"` → skips auto-detection branch
3. Falls through to `_get_cached_client(is_vision=True)` → `resolve_provider_client()` cannot resolve `custom:*` + `is_vision=True` → returns None
4. `None` → RuntimeError

**Key insight:** Non-vision auxiliary tasks (web_extract, compression, etc.) work fine with empty `base_url` because their code path uses `_get_cached_client(is_vision=False)`, which correctly resolves named providers. Only the vision path has this extra `base_url` branch.

**Fix:** Explicitly set `auxiliary.vision.base_url` to `https://{your_domain}/v1`. Even though the provider already defines `base_url`, the vision resolution path does not fall back to the provider's `base_url`.

**Warning:** After modifying Hermes config (including `yaml.dump` rewrites), always verify `auxiliary.vision.base_url` is not empty.

---

### Hermes Providers Key Mismatch Causes 120s Timeout Fallback

**Status:** Fixed — providers key changed from `local-llm` to `custom:local-llm`

**Affected scenario:** Hermes config where `model.provider = "custom:local-llm"` but `providers` dict key was `local-llm` (missing `custom:` prefix).

**Symptom:** Long-context requests (>120K tokens) consistently fail at ~120s, even though `request_timeout_seconds` is set to 3600. Short requests work fine, making the issue hard to diagnose.

**Root cause chain:**
1. Hermes calls `get_provider_request_timeout("custom:local-llm", "278")` to look up the timeout
2. The function searches the `providers` dict by the full key (including `custom:` prefix)
3. If the key is `local-llm` instead of `custom:local-llm`, lookup returns `None`
4. `None` → falls back to hardcoded `HERMES_STREAM_READ_TIMEOUT = 120s`
5. Similarly, `get_provider_stale_timeout()` returns `None` → falls back to `HERMES_STREAM_STALE_TIMEOUT = 180s`
6. 131K-token prefill takes ~1103s on 278 model → killed at 120s

**Fix:** Change `providers` dict key from `local-llm` to `custom:local-llm` to match `model.provider`. Verify with:
```python
get_provider_request_timeout("custom:local-llm", "278")  # should return 3600.0, not None
get_provider_stale_timeout("custom:local-llm", "278")     # should return 3600.0, not None
```

**Warning:** The `providers` key **must exactly match** `model.provider`, including the `custom:` prefix. This is not documented in Hermes and easy to overlook.

---

*Tested on {your_machine} · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9592 Vulkan · 2026-06-03 · Updated 2026-06-13 (both models ubatch=256; INI: kv-unified=1, cache-ram=16384/4096, reasoning-budget=16384, slot-prompt-similarity=0.8, sampling params; systemd: wrapper script + ExecStartPost checkpoint restore; models-max 2; Hermes: title_generation→278)*
