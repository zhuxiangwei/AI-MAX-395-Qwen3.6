# Strix Halo LLM Deploy — Qwen3.6

**[English](./README.md)** | **[中文](./README.zh-CN.md)**

Deploy Qwen3.6 large language models on AMD Ryzen AI Max+ 395 (Strix Halo) with llama.cpp + Vulkan, and serve the inference API over the internet via SSH reverse tunnel + Nginx HTTPS.

---

## Performance Benchmarks

All benchmarks measured on {your_machine} (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9692 Vulkan). Speeds via API `timings` (server-side, excludes network). Gen speed includes thinking tokens.

**Benchmark environment:** CPU governor=performance, `processor.max_cstate=1`, `vm.swappiness=1`, `vm.overcommit_memory=1`, GTT 120GB, mlock=1. These system-level optimizations improve gen speed and prefill stability vs the default powersave governor.

### 35B-A3B MoE (UD-Q8_K_XL, alias `358`)

**Auxiliary model — Hermes auxiliary tasks (vision, compression, etc.).** MoE activates only 3B/35B params per token. ~50 t/s generation with vision support.

**Optimal config: F16 KV cache, UB=256.** UB=256 is the current production config (stable across all context lengths). Previously UB=512 was optimal for ≤128K (+22~25% prefill, -17~20% TTFT), but UB=256 is now unified for all models.

**Ruled out:** UB=128 (MTP 86%→65%, gen slower); UB≥1024 (p256K prefill -44%, TTFT +80%); Q8_0 KV (dequant overhead > bandwidth savings for sparse KV; all Q8_0 UBs slower than F16 UB=256); UB≥2048 (Vulkan crash at 128K+).

#### F16 KV UB=256 (production config, b9692)

**Generation speed by context length** (1468 tasks, cache-ram=65536):

| Context | Tasks | P50 (t/s) | Mean (t/s) |
|---------|-------|-----------|------------|
| <4K | 1227 | 53.3 | 52.8 |
| 4–16K | 171 | 48.3 | 49.0 |
| 16–64K | 48 | 47.2 | 48.3 |
| 64–130K | 18 | 44.2 | 45.0 |
| 130–200K | 4 | 37.8 | 37.9 |

**Prefill speed by prompt length** (1083 tasks, tokens ≥ 100, cache-ram=65536):

| Prompt | Tasks | P50 (t/s) | Mean (t/s) |
|--------|-------|-----------|------------|
| <1K | 625 | 240.8 | 251.6 |
| 1K–5K | 235 | 312.1 | 316.4 |
| 5K–10K | 102 | 290.4 | 290.5 |
| 10K–30K | 79 | 305.7 | 337.8 |
| 30K–60K | 17 | 347.7 | 356.6 |
| 60K–130K | 21 | 407.9 | 365.0 |
| 130K+ | 4 | 309.7 | 309.6 |

> Production workload log data (F16 KV, UB=256, cache-ram=65536, llama.cpp b9692). MTP acceptance: mean 86.8%, median 88.2%. KV cache at ~130K tokens: ~318 MiB (~2.4 KB/token due to MoE sparse heads). Checkpoint eviction observed (143 erased/225 created), indicating cache-ram is adequate for single-conversation workloads but cross-conversation cache reuse limited by Qwen3 SWA architecture.
>
> **Historical reference (b9625, 201 tasks):** Gen P50: <4K=55.4, 4–16K=50.3, 16–64K=55.2, 64–130K=48.1, 130–200K=43.7. Cold-start prefill P50: <4K=453.8, 4–16K=418.0, 16–64K=313.9, 64–130K=236.0, 130–200K=222.9. Gen speed nearly identical across b9625/b9692; prefill P50 lower in b9692 data due to higher cache-hit ratio in larger sample (old data was cold-start only).
>
> **Historical reference (F16 KV UB=512, superseded):** p128=56.7, p4K=56.7, p32K=50.1, p64K=46.7, p128K=38.0, p256K=28.4 t/s gen; 371–931 t/s prefill. Gen speed nearly identical across UB=256/512 (±2 t/s); UB choice mainly affects prefill/TTFT.

### 27B Dense Q8 (Q8_K_XL, alias `278`)

Dense model — all 27B params active per token. Current Hermes default model.

**Config: F16 KV + UB=256 + kv-unified=1 + cache-ram=49152 + slot-prompt-similarity=0.8.**

**Ruled out:** Q8_0 KV (1.7–2× KV space vs Q4_0, no significant prefill advantage); Q4_0 KV (Vulkan dequantization overhead negates bandwidth savings); UB≥1024 (long-context prefill degradation 11–34%); UB≥2048 (Vulkan crash).

#### F16 KV UB=256 (current config, b9692)

**Generation speed by response length** (1001 tasks, decoded ≥ 100 tokens):

| Response length | Tasks | Avg (t/s) | P50 (t/s) |
|----------------|-------|----------|----------|
| <200 tokens | 237 | 11.6 | 11.7 |
| 200–500 | 395 | 11.7 | 11.8 |
| 500–1K | 178 | 10.7 | 10.5 |
| 1K–3K | 149 | 10.7 | 10.4 |
| 3K–5K | 23 | 10.7 | 10.8 |
| 5K+ | 19 | 10.0 | 10.0 |

**Generation speed by context length** (1183 tasks):

| Context | Tasks | P50 (t/s) | Mean (t/s) |
|---------|-------|-----------|------------|
| <4K | 837 | 10.9 | 11.2 |
| 4–16K | 258 | 11.8 | 11.8 |
| 16–64K | 71 | 12.7 | 12.3 |
| 64–130K | 13 | 10.0 | 10.2 |
| 130–200K | 4 | 8.5 | 8.5 |

**Prefill speed by prompt length** (1033 tasks, tokens ≥ 100):

| Prompt length | Tasks | Avg (t/s) | P50 (t/s) |
|--------------|-------|----------|----------|
| <1K | 397 | 60.5 | 38.1 |
| 1K–5K | 333 | 78.9 | 40.2 |
| 5K–10K | 147 | 84.9 | 54.0 |
| 10K–30K | 126 | 122.0 | 132.6 |
| 30K–60K | 13 | 91.1 | 93.2 |
| 60K–130K | 13 | 78.8 | 63.9 |
| 130K+ | 4 | 39.9 | 39.3 |

> † Production workload log data (F16 KV, UB=256, cache-ram=49152, llama.cpp b9692, 1001 gen + 1033 prefill tasks). Gen speed includes thinking tokens. Short/medium context: gen stable at 11–13 t/s; long context (5K+ decoded): 8–10 t/s. Prefill varies widely with cache-hit rate; short contexts (<5K) show low P50 due to incremental cache-hit prefills. True cold prefill at 16K+: 150–226 t/s (median ~200 t/s). At 130K+: ~45 t/s. MTP acceptance: mean 87.1%, median 89.2%.
>
> **Historical reference (b9625, 378 gen + 413 prefill tasks):** Gen avg by response: <200=11.7, 200–500=12.0, 500–1K=10.8, 1K–3K=10.2, 3K–5K=10.1, 5K+=9.2. Prefill avg by prompt: <1K=50, 1K–5K=71, 5K–10K=79, 10K–30K=132, 30K–60K=62, 60K–130K=91, 130K+=46. Gen speed consistent across b9625→b9692; prefill shows similar patterns with larger sample.
>
> **Historical reference (Q8_0 KV UB=512, superseded):** p128=127.4, p4K=247.3, p32K=194.6, p64K=160.2, p128K=119.1, p256K=82.8 t/s prefill; gen 7.3–13.8 t/s.

### Cross-Model Comparison (Optimal Configs)

| Prompt | 35B UD-Q8 | 27B Q8 |
|--------|-----------|--------|
| p128 Gen | 56.7 | 13.8 |
| p4K Gen | 56.7 | 13.4 |
| p32K Gen | 50.1 | 12.5 |
| p64K Gen | 46.7 | 12.1 |
| p128K Gen | 38.0 | 10.0 |
| p256K Gen | 29.3† | 7.3 |
| p256K TTFT | 999s† | 3022s |

> Configs: 35B Q8 = F16 KV (≤128K: UB=512, †256K: UB=256), 27B Q8 = Q8_0 KV UB=512. Gen speeds include thinking tokens.

### Intelligence Test (35B MoE, MTP enabled)

8 questions covering math, logic, CS, and philosophy. Scored by keyword matching (max 10 per question, total 80). Model uses F16 KV + UB=512 + MTP (`--spec-type draft-mtp --spec-draft-n-max 2`).

| Question | 358 (Q8) |
|----------|----------|
| Gaussian sum (1+2+...+100) | 10/10 |
| Syllogism validity | 4/10 |
| Binary search complexity | 3/10 |
| River crossing puzzle | 10/10 |
| Quantum entanglement | 3/10 |
| Definite integral ∫₀¹x²dx | 3/10 |
| Liar paradox | **10/10** |
| LRU cache design | 10/10 |
| **Total** | **53/80** |
| Avg Gen speed | 57.3 t/s |

### Vision Test (35B MoE + mmproj, MTP enabled)

Model uses `mmproj-F16.gguf` (899 MB, qwen35moe architecture). Images sent as base64 via OpenAI chat completions API. F16 KV + UB=512 + MTP.

| Image | Prompt tokens | Gen (t/s) | MTP accept rate | Elapsed |
|-------|-------------|-----------|----------------|---------|
| Baby sleeping (83 KB) | 939 | 51.2 | 50.9% | 18.3s |
| Outdoor photo (1.4 MB) | 2059 | 49.3 | 48.2% | 28.4s |
| Birthday photo (2.8 MB) | 4034 | 53.5 | 55.2% | 39.9s |

> Vision mode MTP accept rate (48–57%) is significantly lower than text mode (60–70%), as visual tokens are harder to predict. The model accurately describes image contents.

---

## Optimization Parameters

### Key Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Service = server-level, INI = model-level | Clean separation; change model params without touching service file |
| Unified parallel=1, ctx=262144 | Simplifies config; single-user workloads; single-model mode `--models-max 1`; 256K context covers all prompt lengths |
| Unified UB=256 | All models use ubatch=256 for stability. 278 UB=512 previously caused instability; unified to UB=256. UB≥1024 causes long-context prefill degradation; UB≥2048 Vulkan crash |
| `cache-ram = 49152/65536` (per-model in INI) | Prompt cache enabled per model: 278=48 GB (primary, long conversations + single-model mode), 358=64 GB (auxiliary, configured for future use). Single-model mode (`models-max 1`) dedicates all GTT to one model, allowing larger cache-ram. Previously `16384/4096` in dual-model mode |
| `reasoning-budget = 16384` (per-model in INI) | Prevents thinking tokens from exhausting KV cache/VRAM while allowing longer reasoning chains. Previously 8192, doubled for better reasoning quality |
| No `reasoning-format = none` | This parameter puts thinking content into `delta.content` instead of `delta.reasoning_content`, causing SSE clients (like OpenClaw/QClaw) to mix thinking with the actual response, leading to duplicate output. Do not add it |
| All models: `parallel = 1`, `ctx-size = 262144` | 256K context per slot; single-user workload never needs concurrent slots; `parallel > 1` wastes KV cache memory |
| Service: `--models-max 1` | Single-model mode: only 278 loaded (primary). 358 available for manual switch (8-17s cold load). Previously `models-max 2` (dual-model resident) caused GTT memory pressure; switched to single-model with larger per-model cache-ram (49152 for 278). Slot-save-path provides KV checkpoint persistence across switches |
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
| `cache-ram` | 278=`49152`, 358=`65536` (per-model in INI) | Prompt cache sized per model role: 278 (primary, 48 GB) in single-model mode; 358 (auxiliary, 64 GB) for future dual-model. Previously `16384/4096` in dual-model mode; `--cache-ram -1` caused unbounded growth (see Known Issues) |
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
| llama.cpp | b9692 (commit 35b1d5791, Vulkan backend) |
| Build options | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` |

> ⚠️ **Version upgraded from b9315 → b9592 (2026-06-11) → b9617 (2026-06-13) → b9625 (2026-06-14) → b9692 (2026-06-18).** Notable changes: Vulkan contiguous buffer fast path (#23973), Vulkan memcpy pipeline barriers (#23770), server checkpoint pos_next fix (#24411), reasoning-budget WebUI precedence fix (#24517), router mode log cleanup (#24463), Vulkan non-contig unary/glu ops fix (#24215), Jinja template bug fixes (#24574, #24580), server UI static asset refactor (#24550), Vulkan host-visible memory buffers on UMA. Commit `6c4cbdc70` ("server: MTP layer kv-cache should respect draft type ctk") is still present, but the current deployment uses default F16 KV cache (no explicit `cache-type-k`/`cache-type-v` in INI), so this bug **does not trigger**. It would only manifest if quantized KV (e.g. `q8_0`, `q4_0`) is re-enabled. Do not enable quantized KV on the Vulkan backend until upstream fixes this.

| Vulkan runtime | 1.4.341 |
| API protocol | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |

**Building llama.cpp:**

```bash
cd ~/llama.cpp
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
| llama-server binary | `$HOME/llama.cpp/build/bin/llama-server` |
| Router preset (all models) | `$HOME/model/router-preset.ini` |

### Model Inventory

Router Mode serves all models from `$HOME/model/`. Single-model mode (`--models-max 1`): 278 loaded by default; 358 available for manual switch (8-17s cold load). Each model has an **alias** for short-name routing.

**Model sources (HuggingFace):**

| Source | Short | Models | Description |
|--------|-------|--------|-------------|
| [unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | **UD-35B** | 358 | Unsloth Dynamic quant for 35B MoE |
| [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) | **UD-27B** | 278 | Unsloth Dynamic quant for 27B Dense |

| Alias | File | Source | Quant | Arch | Size | Active Params | Role |
|-------|------|--------|-------|------|------|---------------|------|
| **358** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | UD-35B | UD-Q8_K_XL | **MoE** | ~37 GB | 3B | Auxiliary (Hermes auxiliary tasks, vision) |
| **278** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | UD-27B | UD-Q8_K_XL | Dense | ~33 GB | 27B | Primary (Hermes default + fallback) |

> **Alias naming convention:** UD models use 3 digits = model size + quant level (e.g. `358` = 35B Q8, `278` = 27B Q8). Both alias and full filename work in API requests.
>
> **Deployment mode:** Single-model mode (`models-max 1`): 278 loaded by default; 358 available for manual switch (8-17s cold load). Per-model `cache-ram` limits (278=49152, 358=65536) sized for single-model GTT budget. GTT 120GB + mlock=1. No `--sleep-idle-seconds`.

### 1. Cloud Nginx Configuration

**File:** `/etc/nginx/sites-enabled/default` (LLM-relevant sections)

```nginx
# nginx.conf key settings
server_tokens off;
gzip off;
limit_req_zone $binary_remote_addr zone=api:10m rate=60r/m;

server {
    listen 443 ssl default_server;
    client_max_body_size 64m;
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

    # LLM Inference API — SSH tunnel port 8080 → llama-server
    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        limit_req zone=api burst=20 nodelay;

        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Nginx timeout 3600s; Hermes-side timeout 7200s
        proxy_read_timeout 3600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;

        # SSE streaming
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        gzip off;
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

**Key points:**
- `/v1/` proxies to `127.0.0.1:8080` (SSH tunnel → inference server)
- `client_max_body_size 64m` for long prompts
- SSE requires `proxy_buffering off` + `gzip off`
- Nginx timeout 3600s; Hermes-side timeout 7200s (Hermes handles its own reconnection)

**Apply:** `sudo nginx -t && sudo systemctl reload nginx`

### 2. Cloud SSH Server

**File:** `/etc/ssh/sshd_config`

```sshd_config
AllowTcpForwarding yes
ClientAliveInterval 60
ClientAliveCountMax 3
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

> ⚠️ Check `/etc/ssh/sshd_config.d/` for drop-in files that may override the main config.

**Apply:** `sudo systemctl restart ssh`

**Verify:** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|passwordauthentication|pubkeyauthentication"`

### 3. SSH Reverse Tunnel (systemd)

**File:** `~/.config/systemd/user/llm-tunnel.service`

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

```bash
mkdir -p ~/.config/systemd/user
systemctl --user daemon-reload
systemctl --user enable llm-tunnel
systemctl --user start llm-tunnel
loginctl enable-linger
```

### 4. Swap Configuration (Ubuntu)

```bash
# Create 32 GB swap file
sudo fallocate -l 32G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

> 32 GB swap provides safety margin for model cold-load memory spikes. With models resident, actual swap usage is minimal (~17 MB observed).

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
chmod +x ~/scripts/gpu-temp-log.sh
systemctl --user daemon-reload
systemctl --user enable --now gpu-temp-log.timer
```

**Sample output:**
```
2026-06-03 13:25:28 | GPU 82°C (junc N/A, mem N/A) | 100% busy | 108W | RAM 106.0/124.9GB
```

> **Note:** Junction and memory temperatures are not available on this APU. GPU edge temperature (`temp1_input`) is the primary monitoring metric. Observed range under full inference load: 78–82°C (TjMax 100°C).

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
cache-ram = 49152
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

[Qwen3.6-35B-A3B-UD-Q8_K_XL]                # alias: 358 — auxiliary (manual switch, vision-capable)
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
cache-ram = 65536
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

> The service uses a wrapper script (`llama-router.sh`) that handles SIGTERM cleanup (saves KV checkpoint before exit) and logs output. `ExecStartPost` automatically restores the last checkpoint on startup. The wrapper runs `llama-server` with `--models-max 1` (single-model mode, 278 loaded by default) and `--models-preset` (per-model params from INI). Model parameters (cache-ram, ubatch, etc.) are defined in the preset INI, not in the service file. GTT 120GB + mlock=1 ensures model weights stay in physical memory. `LimitMEMLOCK=infinity` allows mlock of all model weights. `TimeoutStartSec=300` prevents systemd from killing the service during long model loads.

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

[Hermes](https://github.com/nicobailon/hermes-agent) v0.17.0 — terminal AI agent with TUI, oneshot mode, multi-platform Gateway, MCP, Skills, and cron scheduling.

**Install path:** `~/.hermes/` on WSL Ubuntu 26.04

**Config file:** `~/.hermes/config.yaml` — single-machine deployment, 278 as default model, auxiliary tasks all use 278.

| Config Key | Value |
|---|---|
| **model.default** | `278` (27B Dense) |
| **providers.models** | `278` |
| **supports_vision** | `false` (278 has no vision capability) |
| **auxiliary tasks** | all → `278`, auxiliary tasks disable thinking |
| **fallback_model** | `{provider: local-llm, model: '278'}` |

**Key config:**
- Provider: `local-llm` → `https://{your_domain}/v1`
- `key_env: DASHENZHIYAN_API_KEY` (set in `~/.hermes/.env`)
- `context_length: 262144`, `max_output_tokens: 32768`, `max_tokens: 32768`
- `request_timeout_seconds: 7200`, `stale_timeout_seconds: 7200` (aligned with full-chain timeout)
- `agent.gateway_timeout: 7200`, `approvals.timeout: 7200`, `approvals.gateway_timeout: 7200`
- `chat_template_kwargs.enable_thinking: true` (main), `false` (auxiliary)
- `compression: threshold=0.80, target_ratio=0.30, protect_last_n=20`
- `streaming.enabled: true` (gateway bot streaming)
- `approvals.mode: auto`

**Environment variable overrides** (`~/.hermes/.env`):
```bash
HERMES_STREAM_READ_TIMEOUT=7200   # override hardcoded 120s default
HERMES_STREAM_STALE_TIMEOUT=7200  # override hardcoded 180s default
```

**⚠️ Pitfalls:**
- `providers` key must be `local-llm` (v0.17.0), not `custom:local-llm` (v0.15.1). Mismatch → timeout falls back to 120s
- `auxiliary.vision.base_url` must be explicit (empty string → RuntimeError on vision tasks)
- `fallback_model` must be dict `{provider: ..., model: ...}`, not bare string
- `yaml.dump` may drop bare string values (e.g. `fallback_model: '278'` → empty); verify after rewrite

**Usage:**
```bash
wsl                                    # enter WSL
hermes                                 # TUI mode (interactive)
hermes -z 'quick question'             # oneshot mode
```

**TUI commands:** `/skills` list skills, `/help` all commands, `Ctrl+C` interrupt, `Ctrl+D` or `/exit` quit.

#### opencode (WSL)

[opencode](https://opencode.ai) — terminal-based AI coding agent, configured to use the local inference server.

**Config file:** `~/.config/opencode/opencode.jsonc`

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "local-llm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "本地推理机",
      "options": {
        "baseURL": "https://dashenzhiyan.com/v1",
        "apiKey": "{your_api_key}",
        "timeout": 7200000,
        "chunkTimeout": 7200000
      },
      "models": {
        "Qwen3.6-27B-UD-Q8_K_XL": {
          "name": "Qwen3.6-27B Dense (278)",
          "reasoning": true,
          "limit": {
            "context": 262144,
            "output": 32768
          }
        }
      }
    }
  },
  "model": "local-llm/Qwen3.6-27B-UD-Q8_K_XL",
  "small_model": "local-llm/Qwen3.6-27B-UD-Q8_K_XL"
}
```

**Key points:**
- Primary model (`model`): 278 (27B Dense) with reasoning enabled
- Auxiliary model (`small_model`): 278 (same as primary, reuses loaded model, zero latency)
- context=262144, output=32768
- Timeout: 7200000ms (7200s), aligned with Hermes and llama-server

#### QClaw

QClaw (OpenClaw) — personal AI assistant with multi-channel support (WeChat, QQ, webchat).

- **Provider:** `qclaw` → `http://127.0.0.1:19000/proxy/llm` (cloud proxy with model routing)
- **Default model:** `qclaw/pool-glm-5.1` (cloud proxy, does not directly hit inference server)
- **Channels:** `wechat-access` (QQ), `openclaw-weixin` (WeChat local)

#### TTS Voice Synthesis Service

Qwen3-TTS 1.7B CustomVoice model runs on pure CPU, providing voice output for the monitoring broadcast system and voice assistant. Supports 9 preset speakers (including Chinese female voices vivian/serena).

| Item | Details |
|------|---------|
| Model | Qwen3-TTS-12Hz-1.7B-CustomVoice |
| Path | `/home/zxw/model/Qwen3-TTS-12Hz-1.7B-CustomVoice/` |
| Service | systemd user service `qwen-tts.service` (port 12348, enabled) |
| Startup script | `/home/zxw/scripts/qwen-tts.sh` |
| Startup params | `-S` (streaming mode) |
| Performance | RTF ~1.8-2.5 (pure CPU 8 threads), short text ~2.9s |
| Memory | ~3.2 GB |

**Preset speakers:**

| Speaker | Language | Gender |
|---------|----------|--------|
| vivian | Chinese | Female |
| serena | Chinese | Female |
| ryan | Chinese | Male (default) |
| uncle_fu | Chinese | Male |
| dylan | Chinese | Male |
| eric | Chinese | Male |
| ono_anna | Japanese | Female |
| sohee | Korean | Female |
| jessica | English | Female |

> ⚠️ Previously using Base model with empty `spk_id`, speaker parameter was ignored and all output was default male voice. CustomVoice model includes preset speaker mappings. Base model retained at `/home/zxw/model/Qwen3-TTS-12Hz-1.7B-Base/` but no longer loaded.

**API endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/tts` | POST | Non-streaming synthesis, returns complete WAV |
| `/v1/tts/stream` | POST | Streaming synthesis, returns chunks as generated |
| `/v1/audio/speech` | POST | OpenAI-compatible interface |

**Request example:**

```bash
curl -s -X POST http://127.0.0.1:12348/v1/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Monitoring started","speaker":"vivian","language":"chinese","seed":42}' \
  -o /tmp/tts_out.wav
```

**Audio playback:**

The inference box has a built-in speaker (card1 ALC245 Analog), played via ALSA:

```bash
# Play (non-blocking, detached from SSH session)
systemd-run --user --no-block aplay -q -D plughw:1,0 /tmp/tts_out.wav
```

**ALSA config:** `/etc/asound.conf` sets `defaults.pcm.card=1`, `defaults.ctl.card=1`.

> ⚠️ Do not use `< /dev/null` redirection when playing audio over SSH (hangs the session). Use `systemd-run --user --no-block` to fully detach.

#### Qwen3-ASR Speech Recognition Service

Qwen3-ASR 1.7B model runs on pure CPU for speech-to-text, providing voice input for the voice assistant pipeline.

| Item | Details |
|------|---------|
| Model | `Qwen3-ASR-1.7B-Q8_0.gguf` (2.1 GB) |
| mmproj | `mmproj-Qwen3-ASR-1.7B-Q8_0.gguf` (340 MB) |
| Service | systemd user service `llama-asr.service` (port 12347, enabled, active) |
| Startup script | `/home/zxw/scripts/llama-asr.sh` |
| Inference | Pure CPU (`n-gpu-layers=0`), does not occupy GPU |
| Context | `ctx-size=65536` (full model training context) |
| Threads | 8 |
| Timeout | 600s |
| Performance | prompt eval 199.95 t/s, eval 36.29 t/s |
| API | OpenAI-compatible (llama-server) |

**Service file:** `~/.config/systemd/user/llama-asr.service`

```ini
[Unit]
Description=Qwen3-ASR-1.7B STT Service
After=network.target

[Service]
Type=simple
ExecStart=/home/zxw/scripts/llama-asr.sh
LimitMEMLOCK=infinity
Restart=on-failure
RestartSec=10
TimeoutStartSec=120
TimeoutStopSec=15
KillMode=process

[Install]
WantedBy=default.target
```

**Startup script:** `/home/zxw/scripts/llama-asr.sh`

```bash
#!/bin/bash
# ASR 纯 CPU 推理（不占用 GPU，避免影响大模型）
# ctx-size 65536 = 模型完整训练上下文

LOGDIR="/home/zxw/logs/llama"
BINDIR="/home/zxw/llama.cpp/build/bin"
SERVER="$BINDIR/llama-server"
MODEL="/home/zxw/model/Qwen3-ASR-1.7B-Q8_0.gguf"
MMPROJ="/home/zxw/mmproj/mmproj-Qwen3-ASR-1.7B-Q8_0.gguf"
PORT=12347

export LD_LIBRARY_PATH="$BINDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

mkdir -p "$LOGDIR"

exec "$SERVER" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --model "$MODEL" \
  --mmproj "$MMPROJ" \
  --ctx-size 65536 \
  --n-gpu-layers 0 \
  --threads 8 \
  --timeout 600 \
  >> "$LOGDIR/asr.log" 2>&1
```

> ASR runs entirely on CPU to avoid competing with GPU-bound LLM inference. The 65536 context covers the model's full training context length.

### ai-station-angle

Application suite located in the repository at `ai-station-angle/`, providing monitoring broadcast and voice assistant capabilities for the inference station.

**Files:**
- `monitor-broadcast.py` — Monitoring broadcast system script
- `voice_assistant.py` — Voice assistant main program (Mic → VAD → ASR → LLM → TTS → Speaker)
- `mic_recorder.py` — Microphone recording module (ALSA + energy VAD)
- `asr_module.py` — ASR speech recognition module (port 12347)
- `llm_module.py` — LLM dialogue module (port 12346, tool calling)
- `tts_module.py` — TTS speech synthesis module (port 12348)
- `tools.py` — Tool definitions and execution (6 tools: time/system info/search/weather/web/calculator)
- `voice_assistant_monitor_requirements.md` — Requirements document

**Monitoring Broadcast System (v7, production):**

Automated monitoring and TTS broadcast service that monitors LLM inference status and hardware health in real-time.

| Item | Details |
|------|---------|
| Script | `ai-station-angle/monitor-broadcast.py` |
| Service | systemd user service `monitor-broadcast.service` (enabled, Restart=on-failure) |
| State file | `~/.config/monitor-broadcast/state.json` |

**Dual-frequency polling architecture:**

| Poll type | Interval | Monitors |
|-----------|----------|----------|
| Fast poll | 180s | Model switching, inference task lifecycle (start/prefill complete/generation milestones/end/idle) |
| Slow poll | 300s | Hardware alerts (GPU temp/RAM/power), log E/F level entries, daily broadcast |

**Daily broadcast interval:** 30 minutes.

**Alert thresholds:**

| Metric | WARN | CRIT |
|--------|------|------|
| GPU temperature | 80°C | 90°C |
| Memory usage | 80% | 90% |
| GPU power | 120W | 130W |

**Log alert keywords:** OOM, Xid, segfault, Vulkan crash (`vk::DeviceLostError`), subprocess crash, Fatal, Error. 5-minute deduplication on severity-3 alerts.

**TTS broadcast queue:**
- Queue limit: 3 items (overflow drops new items)
- CRIT alerts (severity ≥ 3) jump to queue head
- Playback: streaming pre-buffer mode — estimates audio duration, pre-fills 80% buffer, then starts `aplay` via FIFO pipe while TTS continues streaming
- No fallback to non-streaming TTS (removed in production); if streaming fails, the broadcast is skipped

**System volume:** ALSA Master 95%, TTS engine does not manage volume.

**Core constraint:** ASR and TTS run on pure CPU; LLM runs on GPU. This ensures voice processing never competes with LLM inference for GPU resources.

**Voice assistant pipeline (implemented):** Microphone → VAD → ASR (port 12347) → LLM (port 12346, 35B-A3B dedicated instance with tool calling) → TTS (port 12348) → Speaker. Full pipeline code complete, pending integration testing.

**Monitoring broadcast pipeline (active):** Independent thread monitors hardware (GPU/CPU/RAM) + log alerts → TTS broadcast.

**State persistence:** `~/.config/monitor-broadcast/state.json` stores file offsets, alert cooldowns, current model/port, and broadcast metadata. Transient state (`_active_task`, `_last_gen_milestone`) is runtime-only and not persisted.

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
- [ ] Single-model mode: 278 loaded; 358 available for manual switch (8-17s cold load)
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

**Affected models:** 27B Dense series (alias `278`). 35B MoE models (alias `358`) are **not** affected.

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
/home/$USER/llama.cpp/ggml/src/ggml-backend.cpp:348: GGML_ASSERT(tensor->data != NULL && "tensor not allocated") failed
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

**Status:** Resolved — removed `--sleep-idle-seconds`; current deployment uses single-model mode (`models-max 1`)

**Historical scenario:** Dual-model resident mode (`models-max 2`) with `--sleep-idle-seconds`. Idle-unload/reload cycle caused memory spike exceeding 128 GB RAM → OOM Kill. Resolved by switching to single-model mode without `--sleep-idle-seconds`.

### `reasoning=off` Causes Catastrophic Checkpoint Restore Slowdown

**Status:** Fixed — removed `reasoning = off` and `reasoning-budget = 0` from model presets, replaced with `reasoning-budget = 8192`

**Root cause:** `reasoning = off` creates an attention mask mismatch between the checkpoint and runtime configuration. When restoring a prompt cache checkpoint, llama-server detects the mismatch and falls back to slow re-prefilling.

**Warning:** Do **not** re-add `reasoning = off` to any model preset. Always keep reasoning enabled at the server level and control it per-request via `chat_template_kwargs: { enable_thinking: false }`.

---

### MTP + Quantized KV Cache Causes Vulkan DeviceLost (b9318+)

**Status:** Open — version locked at b9315; awaiting upstream fix

**Affected models:** All models with MTP speculative decoding + quantized KV cache (`cache-type-k` / `cache-type-v`). Current deployment uses default F16 KV (no explicit `cache-type-k`/`cache-type-v` in INI), so this issue is **not currently triggered**. It would only manifest if quantized KV (e.g. `q8_0`, `q4_0`) were re-enabled on any model.

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

**Workaround:** Upgraded to b9692 (F16 KV does not trigger this bug). Do **not** enable quantized KV types until upstream addresses the Vulkan + quantized KV cache interaction.

**Upstream tracking:** No issue filed yet. The regression is specific to Vulkan backend + MTP + quantized KV; other backends (CPU/CUDA/Metal) are unaffected.

---

### `--cache-ram -1` Causes VRAM Contention and 35B Cold-Load Stall

**Status:** Mitigated — prompt cache now per-model in INI (278 `cache-ram = 49152`, 358 `cache-ram = 65536`). Single-model mode (`models-max 1`) prevents unbounded growth.

**Symptom:** `--cache-ram -1` allows prompt cache to grow without bound. In single-model mode, 278's cache consumed ~12+ GB, leaving insufficient headroom for 358 cold load (stalled 20+ minutes).

**Fix:** Per-model `cache-ram` limits in INI + single-model mode. **Do not** use `--cache-ram -1` in any mode.

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

**Status:** Fixed — v0.17.0 uses providers key `local-llm` (no `custom:` prefix).

**Affected scenario:** Hermes config where `model.provider = "custom:local-llm"` but `providers` dict key was `local-llm` (missing `custom:` prefix).

**Symptom:** Long-context requests (>120K tokens) consistently fail at ~120s, even though `request_timeout_seconds` is set to 7200. Short requests work fine, making the issue hard to diagnose.

**Root cause chain:**
1. Hermes calls `get_provider_request_timeout("custom:local-llm", "278")` to look up the timeout
2. The function searches the `providers` dict by the full key (including `custom:` prefix)
3. If the key is `local-llm` instead of `custom:local-llm`, lookup returns `None`
4. `None` → falls back to hardcoded `HERMES_STREAM_READ_TIMEOUT = 120s`
5. Similarly, `get_provider_stale_timeout()` returns `None` → falls back to `HERMES_STREAM_STALE_TIMEOUT = 180s`
6. 131K-token prefill takes ~1103s on 278 model → killed at 120s

**Fix:** Ensure `providers` dict key matches `model.provider` exactly. Verify with:
```python
get_provider_request_timeout("custom:local-llm", "278")  # should return 7200.0, not None
get_provider_stale_timeout("custom:local-llm", "278")     # should return 7200.0, not None
```

**Warning:** The `providers` key **must exactly match** `model.provider`, including the `custom:` prefix. This is not documented in Hermes and easy to overlook.

---

*Tested on {your_machine} · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9692 Vulkan · 2026-06-20*
