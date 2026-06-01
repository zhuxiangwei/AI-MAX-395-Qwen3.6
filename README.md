# Strix Halo LLM Deploy — Qwen3.6

**[English](./README.md)** | **[中文](./README.zh-CN.md)**

Deploy Qwen3.6 large language models on AMD Ryzen AI Max+ 395 (Strix Halo) with llama.cpp + Vulkan, and expose the inference API to the internet via SSH reverse tunnel + Nginx HTTPS.

---

## Performance Benchmarks

All benchmarks measured on FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9299 Vulkan). Speeds via API `timings` (server-side, excludes network). Gen speed includes thinking tokens.

### 35B-A3B MoE (UD-Q8_K_XL, alias `358`)

**Primary model — fastest generation, stable at 256K.** MoE activates only 3B/35B params per token.

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

### 35B-A3B MoE APEX I-Quality (alias `aux`, ~22 GB)

APEX quantization — Adaptive Precision for EXpert Models. Mixed-precision per tensor (critical layers Q6_K/Q8_0, middle expert layers Q4_K_M). ~22 GB overall (between Q4 and Q5 by size, but quality matches Q8). imatrix-calibrated with diverse data. **~48% faster than UD-Q8 + MTP, 59% file size.** Now repurposed as the **auxiliary model** (`aux`): reasoning disabled, compact context (64K per slot), with mmproj for vision tasks.

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

### 35B-A3B MoE APEX I-Balanced (alias `35b`, ~24 GB)

APEX quantization — best quality-to-speed tradeoff. Mixed-precision per tensor (critical layers Q6_K/Q5_K_M, middle expert layers Q4_K_M). ~24 GB overall (between Q5 and Q6 by size). KL max 4.53 — **lowest deviation among all quantizations** (even better than Q8's 9.72). imatrix calibration reduces worst-case deviation by 68%.

**Optimal config: F16 KV cache.** Same UB pattern: ≤128K → UB=512; 256K → UB=256.

#### F16 KV UB=512 (optimal ≤128K)

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

### 27B Dense Q8 (Q8_K_XL, alias `278`)

Dense model — all 27B params active per token. Q8_0 KV cache unlocks 256K context and dramatically improves long-context prefill.

**Optimal config: Q8_0 KV + UB=512.**

**Ruled out:** F16 KV (p256K timeout >7200s); Q8_0 UB=256 (p64K+ slower than UB=512); Q8_0 UB≥1024 (p128K TTFT 1139s at UB=512 already slow, degrades further); UB≥2048 (Vulkan crash).

#### Q8_0 KV UB=512

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 13.8 | 127.4 | 1.2s |
| p4K | 13.4 | 247.3 | 31.1s |
| p32K | 12.5 | 194.6 | 187.7s |
| p64K | 12.1 | 160.2 | 432.6s |
| p128K | 10.0 | 119.1 | 1139.0s |
| p256K | 7.3 | 82.8 | 3022.3s |

> p128K elapsed: 1272s. p256K elapsed: 3122s (~52 min). Q8_0 KV p128K prefill +271% vs F16 KV (119 vs 32 t/s, b9210 F16 KV baseline).

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

| Prompt | APEX I-Q (aux) | APEX I-B | 35B UD-Q8 | 27B Q8 | 27B Q6 | 27B Q4 |
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

8 questions covering math, logic, CS, and philosophy. Scored by keyword matching (max 10 per question, total 80). All models use F16 KV + UB=512 + MTP (`--spec-type draft-mtp --spec-draft-n-max 3`).

| Question | aux (I-Q) | 35b (I-B) | 358 (Q8) |
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
| Baby sleeping (83 KB) | 939 | aux | **73.5** | 55.8% | 16.7s |
| | | 35b | 69.6 | 52.4% | 14.6s |
| | | 358 | 51.2 | 50.9% | 18.3s |
| Outdoor photo (1.4 MB) | 2059 | aux | **69.8** | 52.3% | 22.3s |
| | | 35b | 65.4 | 48.4% | 23.4s |
| | | 358 | 49.3 | 48.2% | 28.4s |
| Birthday photo (2.8 MB) | 4034 | aux | 70.5 | 53.9% | 35.2s |
| | | 35b | **71.1** | 56.6% | 35.2s |
| | | 358 | 53.5 | 55.2% | 39.9s |

> Vision mode MTP accept rate (48–57%) is significantly lower than text mode (60–70%), as visual tokens are harder to predict. APEX I-Quality is ~39% faster than UD-Q8 on vision tasks. All three models accurately describe image contents.

---

## Optimization Parameters

### Key Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Service = server-level, INI = model-level | Clean separation; change model params without touching service file |
| Unified 256K context | `-c` only pre-allocates KV cache; no performance impact; one config for all prompt lengths |
| Per-quant differentiated ub | Higher quant = larger weights = less VRAM headroom = smaller ub for stability; optimal UB varies by model (256–1024) |
| No `--cache-ram` | Pinned alloc fails on unified memory and is 4.6% slower; default prompt cache is better |
| `--reasoning-budget 8192` | Prevents thinking tokens from exhausting KV cache/VRAM; no performance cost (main models only) |
| No `reasoning-format = none` | This parameter puts thinking content into `delta.content` instead of `delta.reasoning_content`, causing SSE clients (like OpenClaw/QClaw) to mix thinking with the actual response, leading to duplicate output. Do not add it |
| 35B MoE: `parallel = 3`, `ctx-size = 786432` | 3 concurrent slots, each gets 262K context (ctx-size ÷ parallel); memory sufficient on 128 GB GTT (main models) |
| 27B Q8: `parallel = 2`, `ctx-size = 524288` | 2 concurrent slots (each 262K); single-user scenario |
| 27B Q6/Q4: `parallel = 2`, `ctx-size = 524288` | 2 concurrent slots (each 262K); `parallel = 3` triggers Vulkan bug on 27B Dense models (see Known Issues) |
| `--spec-draft-n-max 3` | 4 is 20.6% slower than 3 |
| `-t 8` for all models | No difference vs `-t 16` with full GPU offload; t=8 runs cooler |
| No `--no-mmap` | No benefit; `--mmap` (default) + `--mlock` is the best combination |
| `-a Qwen3.6` | Sets model name in API responses; required by clients that validate the model field |
| `alias` short names | Convenient routing without symlinks; both alias and filename work |
| Onduty subdirectory (`~/model/onduty/`) | Only 2 models in dir + `models-max 2` = both models always loaded, no LRU eviction; symlinks to parent dir keep single copy of model files |
| aux: `reasoning = off`, compact ctx | Disabling reasoning on aux saves memory + avoids thinking token overhead; 196608 ctx (3 slots × 65K) is sufficient for auxiliary tasks |

### Usage Constraints

| Constraint | Value | Reason |
|-----------|-------|--------|
| 35B MoE max concurrent slots | 3 (`parallel = 3`) | `ctx-size = 786432` (786432 ÷ 3 = 262K per slot) |
| aux (35B APEX I-Q) max concurrent slots | 3 (`parallel = 3`) | `ctx-size = 196608` (196608 ÷ 3 = 65K per slot); reasoning disabled |
| 27B Q8 max concurrent slots | 2 (`parallel = 2`) | `ctx-size = 524288` (524288 ÷ 2 = 262K per slot); single-user scenario |
| 27B Q6/Q4 max concurrent slots | 2 (`parallel = 2`) | `ctx-size = 524288` (524288 ÷ 2 = 262K per slot); `parallel = 3` triggers Vulkan bug |
| 35B MoE: max context | 256K | UB=512 optimal for ≤128K; UB=256 optimal for 256K; UB≥1024 degrades at p256K; UB≥2048 Vulkan crash |
| 27B Dense: max context | 256K (Q8_0 KV) | Q8_0 KV UB=512 (Q8/Q6) / UB=1024 (Q4); F16 KV p256K timeout; UB≥2048 Vulkan crash |
| Thinking mode | Main models: enabled (`reasoning-budget=8192`); aux: disabled (`reasoning=off`) | Budget cap prevents runaway thinking; aux doesn't need thinking for auxiliary tasks |
| No `reasoning-format=none` | Do not add | Causes thinking content to appear in `delta.content` instead of `delta.reasoning_content`, breaking SSE client parsing (see Known Issues) |
| Concurrency | 35B: up to 3, 27B: up to 2 | Multi-slot supported; concurrent requests share GPU compute (~33% t/s each at full load for 35B) |
| No `--cache-ram` | Don't add it | Harmful on unified memory |
| `b` must divide by `ub` | `n_batch % n_ubatch == 0` | llama.cpp requirement |

### Parameter Separation Principle

| Scope | Where | Examples |
|-------|-------|---------|
| **Server-level** | `llm-router.service` ExecStart | `--host`, `--port`, `--api-key`, `--models-dir`, `--models-max`, `--models-preset`, `--timeout`, `--sleep-idle-seconds` |
| **Model-level** | `router-preset.ini` per-model section | `n-gpu-layers`, `ctx-size`, `ubatch-size`, `threads`, `alias`, `spec-type`, `mlock`, `numa`, ... |

> Model parameters are defined **only** in the INI — never duplicated in the service file.

### Preset INI (Per-Model Parameters)

### Onduty Deployment (Dual-Model Persistent)

To keep both the main model (278) and auxiliary model (aux) always loaded without LRU eviction, use a dedicated subdirectory with only 2 models:

```
~/model/onduty/
├── Qwen3.6-27B-UD-Q8_K_XL.gguf → ../ (symlink)
├── Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf → ../ (symlink)
├── mmproj-F16.gguf → ../ (symlink)
└── onduty-preset.ini
```

**Key principle:** Directory has exactly 2 `.gguf` models + `models-max 2` → both models are always loaded. No third model to compete for LRU eviction.

**Setup:**
```bash
mkdir -p ~/model/onduty
cd ~/model/onduty
ln -sf ../Qwen3.6-27B-UD-Q8_K_XL.gguf .
ln -sf ../Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf .
ln -sf ../mmproj-F16.gguf .
# Create onduty-preset.ini (see below)
# Update llm-router.service: --models-dir ~/model/onduty --models-max 2 --models-preset ~/model/onduty/onduty-preset.ini
```

**Memory:** 95.7 GB used / 131 GB total, ~35 GB available, swap ~445 MB. Sufficient headroom.

**File:** `~/model/onduty/onduty-preset.ini`

```ini
[Qwen3.6-27B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 2
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 524288
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 278

[Qwen3.6-35B-A3B-APEX-MTP-I-Quality]
n-gpu-layers = 99
flash-attn = 1
parallel = 3
spec-type = draft-mtp
spec-draft-n-max = 3
mmproj = /home/zxw/model/onduty/mmproj-F16.gguf
mlock = 1
numa = distribute
reasoning = off
reasoning-budget = 0
ctx-size = 196608
batch-size = 4096
ubatch-size = 512
threads = 8
alias = aux
```

### Full Preset INI (All Models)

**File:** `~/model/router-preset.ini`

```ini
[Qwen3.6-35B-A3B-APEX-MTP-I-Balanced]
n-gpu-layers = 99
flash-attn = 1
parallel = 3
spec-type = draft-mtp
spec-draft-n-max = 3
mmproj = /home/zxw/model/mmproj-F16.gguf
mlock = 1
numa = distribute
reasoning-budget = 8192
ctx-size = 786432
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 35b

[Qwen3.6-35B-A3B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 3
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
ctx-size = 786432
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 358

[Qwen3.6-27B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 2           ; ⚠ 3 triggers Vulkan bug (see Known Issues)
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 524288      ; 524288 ÷ 2 = 262K per slot
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 278

[Qwen3.6-27B-UD-Q6_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 2           ; ⚠ 3 triggers Vulkan bug (see Known Issues)
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 524288      ; 524288 ÷ 2 = 262K per slot
batch-size = 4096
ubatch-size = 512
threads = 8
alias = 276

[Qwen3.6-27B-UD-Q4_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 2           ; ⚠ 3 triggers Vulkan bug (see Known Issues)
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
cache-type-k = q8_0
cache-type-v = q8_0
ctx-size = 524288      ; 524288 ÷ 2 = 262K per slot
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
| llama.cpp | b9401 (commit 751ebd17a, Vulkan backend) |
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
| Onduty (always-loaded) models | `$HOME/model/onduty/` |
| llama-server binary | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Router preset (all models) | `$HOME/model/router-preset.ini` |
| Onduty preset (278 + aux) | `$HOME/model/onduty/onduty-preset.ini` |

### Model Inventory

Router Mode serves all models from `$HOME/model/`. Single-model mode (`--models-max 1`): one model loaded at a time, switching via LRU on client request. Each model has an **alias** for short-name routing.

**Model sources (HuggingFace):**

| Source | Short | Models | Description |
|--------|-------|--------|-------------|
| [unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | **UD-35B** | 358 | Unsloth Dynamic quant for 35B MoE |
| [mudler/Qwen3.6-35B-A3B-APEX-MTP-GGUF](https://huggingface.co/mudler/Qwen3.6-35B-A3B-APEX-MTP-GGUF) | **APEX-35B** | 35b, aux | APEX adaptive-precision quant for 35B MoE |
| [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) | **UD-27B** | 278, 276, 274 | Unsloth Dynamic quant for 27B Dense |

| Alias | File | Source | Quant | Arch | Size | Active Params | Role |
|-------|------|--------|-------|------|------|---------------|------|
| **35b** | `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced.gguf` | APEX-35B | APEX mixed | **MoE** | ~24 GB | 3B | Main (quality) |
| **358** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | UD-35B | UD-Q8_K_XL | **MoE** | ~37 GB | 3B | Main (fastest) |
| **aux** | `Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf` | APEX-35B | APEX mixed | **MoE** | ~22 GB | 3B | Auxiliary (vision, fast, no reasoning) |
| **278** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | UD-27B | UD-Q8_K_XL | Dense | ~33 GB | 27B | Main (default) |
| **276** | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | UD-27B | UD-Q6_K_XL | Dense | ~25 GB | 27B | Main |
| **274** | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | UD-27B | UD-Q4_K_XL | Dense | ~17 GB | 27B | Main |

> **Alias naming convention:** APEX main model uses `35b` for balanced, `aux` for auxiliary (I-Quality). UD models use 3 digits = model size + quant level (e.g. `358` = 35B Q8, `276` = 27B Q6). Both alias and full filename work in API requests.
>
> **Onduty deployment** (`~/model/onduty/`): Only 278 + aux are always loaded (`models-max 2`). Other models (358/35b/276/274) are available from the full `~/model/` directory by switching the service config. The `aux` model is a lightweight 35B APEX I-Quality with reasoning disabled, compact context (65K per slot), and mmproj for vision tasks.

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

        # Long timeout (LLM inference is slow)
        proxy_read_timeout 600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;

        # SSE streaming support
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
        gzip off;              # must disable gzip for SSE streaming
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

# Security: key-only auth (disable password login)
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

> ⚠️ **Important:** Ubuntu's `/etc/ssh/sshd_config.d/` directory contains drop-in files (e.g., `50-cloud-init.conf`) that **override** the main config. You must also check and edit files in that directory, or `PasswordAuthentication no` may not take effect. Verify with: `sudo sshd -T | grep passwordauthentication`

**Apply:** `sudo systemctl restart ssh`

**Verify:** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|passwordauthentication|pubkeyauthentication"`

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
ExecStart=/home/zxw/llama/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 --port 12345 \
    --api-key {your_api_key} \
    -a Qwen3.6 \
    --models-dir /home/zxw/model/onduty \
    --models-max 2 \
    --models-preset /home/zxw/model/onduty/onduty-preset.ini \
    --timeout 600 \
    --metrics
Restart=on-failure
RestartSec=10
WorkingDirectory=/home/zxw
LimitMEMLOCK=infinity

[Install]
WantedBy=default.target
```

> **Note:** This uses the **onduty** subdirectory with only 2 models (278 + aux). To switch to the full model directory with all 5 models (single-model LRU mode), change `--models-dir /home/zxw/model`, `--models-max 1`, and `--models-preset /home/zxw/model/router-preset.ini`.

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

### Client Integration

#### Hermes Agent

[Hermes](https://github.com/nicobailon/hermes-agent) v0.15.1 — terminal AI agent with TUI, oneshot mode, multi-platform Gateway, MCP, Skills, and cron scheduling.

**Install path:** `~/.hermes/` on WSL Ubuntu 26.04

**Config file:** `~/.hermes/config.yaml`

```yaml
providers:
  local-llm:
    name: "Local LLM (Strix Halo)"
    base_url: "https://dashenzhiyan.com/v1"
    key_env: "DASHENZHIYAN_API_KEY"
    extra_body:
      chat_template_kwargs:
        enable_thinking: true       # enables thinking mode
    models:
      "358":
        context_length: 262144     # per-slot context (ctx-size ÷ parallel)
        max_output_tokens: 32768
        supports_vision: true
      "278":
        context_length: 262144
        max_output_tokens: 32768
      "276":
        context_length: 262144
        max_output_tokens: 32768
      "274":
        context_length: 262144
        max_output_tokens: 32768
      "35b":
        context_length: 262144
        max_output_tokens: 32768
        supports_vision: true
      "aux":
        context_length: 65536      # 196608 ÷ 3 = 65K per slot
        max_output_tokens: 32768
        supports_vision: true
    request_timeout_seconds: 3600  # API request timeout
    stale_timeout_seconds: 900    # non-stream stale detection

model:
  default: "278"
  provider: "custom:local-llm"
  base_url: "https://dashenzhiyan.com/v1"
  extra_body:
    chat_template_kwargs:
      enable_thinking: true
max_tokens: 32768                 # must ≥ reasoning-budget + expected output

streaming:
  enabled: true                  # gateway bot streaming (editMessage)

compression:
  threshold: 0.80                # trigger compression at 80% context
  target_ratio: 0.30             # keep 30% of threshold as recent tail
```

**Key configuration notes:**
- `provider: "custom:local-llm"` uses the named providers section (not `"custom"` direct-alias, which ignores `extra_body`)
- `key_env: "DASHENZHIYAN_API_KEY"` — API key derived from domain name; must be set in `~/.hermes/.env`
- `supports_vision: true` on 35B MoE models (358/35b have mmproj); 27B Dense models have no vision
- `max_output_tokens: 32768` per model — without this, Hermes defaults to 4096 and truncates long responses
- `max_tokens: 32768` — must be ≥ `reasoning-budget` (8192) + expected output; 8192 caused thinking tokens to consume the entire budget, truncating tool calls and responses
- `chat_template_kwargs: enable_thinking: true` — enables Qwen3.6 thinking mode; omit or set `false` to disable
- `streaming.enabled: true` — enables Gateway bot streaming (editMessageText on Telegram/Discord/Slack)
- `compression.threshold: 0.80` — local inference has no token cost, so delay compression; 0.50 is too aggressive
- `compression.target_ratio: 0.30` — after compression, keep 0.80 × 0.30 × 262K ≈ 63K tokens of recent context
- `request_timeout_seconds: 3600` — long timeout for thinking mode (45–130s thinking + up to 300s generation)
- `context_length: 262144` for all models — this is **per-slot** context (ctx-size ÷ parallel), not total ctx-size

**Usage:**
```bash
wsl                                    # enter WSL
hermes                                 # TUI mode (interactive)
hermes -z 'quick question'             # oneshot mode
hermes -z 'question' --model 35b       # oneshot with specific model
```

**TUI commands:** `/model 358` switch model, `/skills` list skills, `/help` all commands, `Ctrl+C` interrupt, `Ctrl+D` or `/exit` quit.

#### QClaw

QClaw (OpenClaw) — personal AI assistant with multi-channel support (WeChat, QQ, webchat).

**Provider config** (`~/.qclaw/openclaw.json`):
- `myllm` provider → `https://dashenzhiyan.com/v1/`, 6 models (358/278/276/274/35b/aux)
- Per-model: `contextWindow: 262144`, `maxTokens: 32768`, reasoning enabled
- `injectNumCtxForOpenAICompat: false`
- Default model: `qclaw/pool-glm-5.1` (cloud proxy); xiaowei agent uses `myllm/358`

### Verification Checklist

- [ ] Cloud Nginx config updated (with `/v1/` and `/health` endpoints)
- [ ] Cloud SSL certificates configured
- [ ] Cloud `sshd_config` allows TCP forwarding and keepalive
- [ ] Inference box has SSH key for passwordless login to cloud
- [ ] `llm-tunnel.service` created and **active**
- [ ] Cloud: `ss -tlnp | grep 8080` shows tunnel listening
- [ ] `llm-router.service` created and **active** (server-level params only)
- [ ] `~/model/onduty/onduty-preset.ini` configured (278 + aux, onduty mode)
- [ ] `~/model/router-preset.ini` configured with all-model params + aliases (fallback)
- [ ] Cloud: `curl http://127.0.0.1:8080/v1/models` returns models with aliases
- [ ] Onduty mode: both 278 and aux show status `loaded` after first request
- [ ] External: `curl https://{your_domain}/health` returns `OK`
- [ ] Alias routing: `curl -d '{"model":"278",...}'` and `curl -d '{"model":"aux",...}'` both work

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

**Affected models:** 27B Dense series (aliases `278`/`276`/`274`). 35B MoE models (aliases `358`/`35b`/`aux`) are **not** affected.

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
/home/zxw/llama/llama.cpp/ggml/src/ggml-backend.cpp:348: GGML_ASSERT(tensor->data != NULL && "tensor not allocated") failed
```

**Root cause:** Vulkan backend uses device-only (unified) memory buffers. Per-slot KV cache tensors have `tensor->data == NULL` on the host side (data lives on GPU). `ggml_backend_tensor_get()` and related functions unconditionally assert `tensor->data != NULL`, which fails when the prompt cache system attempts to save/restore slot state (including MTP draft context). The crash occurs in two paths:

1. **Direct path:** `ggml_backend_tensor_get()` — `ggml-backend.cpp:348`
2. **MTP draft path:** `common_prompt_checkpoint::update_dft()` → `llama_context::state_seq_get_data()` → `llama_io_write_host` — `common.cpp:2082`

**Affected code** (`ggml/src/ggml-backend.cpp`, 11 occurrences):
```cpp
// Line 348 — one of 11 identical assertions that fail on Vulkan unified memory
GGML_ASSERT(tensor->data != NULL && "tensor not allocated");
```

**Workaround attempted:** `--kv-unified` bypasses crash path #1 but **not** crash path #2 (MTP draft checkpoint). Not viable.

**Current mitigation:** 27B Q8 reduced to `parallel = 1` (single-user scenario, no concurrency needed); 27B Q6/Q4 reduced to `parallel = 2`. This avoids the crash at the cost of reduced concurrent slots.

**Upstream tracking:**
- Issue [#19839](https://github.com/ggml-org/llama.cpp/issues/19839) — original bug report
- PR [#22453](https://github.com/ggml-org/llama.cpp/pull/22453) — proposed fix (add NULL check before assert, delegate to backend `get_tensor`); closed but not merged
- As of b9401 (commit `751ebd17a`), all 11 assert locations remain unchanged in `ggml-backend.cpp`

---

### OOM Kill with Dual-Model + Prompt Cache Accumulation

**Status:** Resolved — onduty subdirectory deployment prevents LRU eviction and OOM

**Affected scenario:** Main model (27B Q8) + aux model coexist in dual-model mode (`models-max 2`), with `parallel = 2` on the main model.

**Symptom:** Linux OOM killer terminates `llama-server` after hours of idle operation. Also, the router's LRU eviction can unload the main model mid-task when aux is loaded, breaking long conversations.

**Root cause chain:**
1. Main model runs with `parallel = 2`, creating 2 independent slots, each accumulating its own prompt cache (up to 8192 MiB per model)
2. After a long session (task #2879, 53969 tokens), slot prompt cache grows to ~2.1 GB
3. Both models loaded with `--mlock` — model weights locked in RAM, cannot be swapped
4. When idle, both models occupy ~75 GB combined (weights + KV cache + prompt cache + MTP context)
5. A new request triggers `prompt_save` which allocates additional memory → exceeds 128 GB RAM + 8 GB swap → OOM Kill

**Key insight:** Prompt cache is **not automatically released** when slots are idle. `--cache-idle-slots` would help, but it requires `--kv-unified` which is incompatible with 27B MTP (triggers Vulkan crash path #2).

**Resolution — Onduty subdirectory:**
- Create `~/model/onduty/` with only 2 model symlinks (278 + aux I-Quality) + dedicated `onduty-preset.ini`
- `models-max 2` with exactly 2 models in directory = both always loaded, no LRU eviction
- aux uses compact config: `reasoning=off`, `ctx-size=196608` (3×65K), saving ~10 GB vs full-size dual-model
- Memory headroom: 95.7 GB used / 131 GB total, ~35 GB available
- Original `~/model/router-preset.ini` and single-model config preserved for fallback

**Fallback:** To use all 5 models with single-model LRU mode, change service config: `--models-dir /home/zxw/model --models-max 1 --models-preset /home/zxw/model/router-preset.ini`

---

*Tested on FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9401 Vulkan · 2026-06-01*
