# Strix Halo LLM Deploy — Qwen3.6

**[English](./README.md)** | **[中文](./README.zh-CN.md)**

Deploy Qwen3.6 large language models on AMD Ryzen AI Max+ 395 (Strix Halo) with llama.cpp + Vulkan, and expose the inference API to the internet via SSH reverse tunnel + Nginx HTTPS.

---

## Performance Benchmarks

All benchmarks measured on FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9210 Vulkan).

### 35B-A3B MoE (Q8_K_XL, alias `358`)

**The primary model — fastest generation, stable at 256K context.** ✅ *Testing complete.*

| Prompt Size | Gen Speed | Prefill Speed | TTFT |
|-------------|-----------|---------------|------|
| 128 tokens | 54.4 t/s | 340.2 t/s | 0.37s |
| 4K tokens | 56.6 t/s | 391.3 t/s | 10.5s |
| 32K tokens | 46.9 t/s | 520.1 t/s | 63.0s |
| 64K tokens | 45.5 t/s | 448.1 t/s | 146.2s |
| 128K tokens | 36.5 t/s | 344.6 t/s | 380.4s |
| 256K tokens | 28.4 t/s | 238.2 t/s | 1015.0s |

> Config: `-c 262144 -b 4096 -ub 256 -t 8`, F16 KV cache, thinking enabled (`reasoning-budget=8192`). Gen speed includes thinking tokens (real usage). MoE activates only 3B of 35B params per token → fastest generation.

<details>
<summary><b>Q8_0 KV Cache + UB Sweep Results</b></summary>

Q8_0 KV cache tested across 4 UB values (512–4096), compared against F16 KV UB=256 baseline.

**Prefill speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 | Q8_0 ub=4096 |
|--------|-----------|-------------|--------------|--------------|--------------|
| p128 | 340.2 | 364.2 | 297.9 | 338.2 | 343.6 |
| p4K | 391.3 | 468.8 | **480.0** | 450.0 | 295.4 |
| p32K | 520.1 | 544.9 | **589.0** | 576.1 | 384.4 |
| p64K | 448.1 | 421.3 | **450.8** | 440.4 | 327.5 |
| p128K | **344.6** | 287.5 | 298.7 | 295.2 | 241.4 |
| p256K | **238.2** | 199.9 | — | — | ❌ crash |

**Gen speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 | Q8_0 ub=4096 |
|--------|-----------|-------------|--------------|--------------|--------------|
| p128 | **54.4** | 51.6 | 53.5 | 52.5 | 53.9 |
| p4K | **56.6** | 51.3 | 50.2 | 52.7 | 47.7 |
| p32K | **46.9** | 45.3 | 46.1 | 43.9 | 46.5 |
| p64K | **45.5** | 43.7 | 40.7 | 41.2 | 42.4 |
| p128K | **36.5** | 34.0 | 33.3 | 33.3 | 33.9 |
| p256K | **28.4** | 24.3 | — | — | ❌ crash |

**Findings:**

1. **Q8_0 KV UB=1024 is the best among Q8_0 configs** — fastest prefill at p4K–p128K, near-optimal gen and TTFT; but still loses to F16 KV at p64K+
2. **Q8_0 KV UB=512 is the only Q8_0 config that completes 256K context** — prefill 199.9 t/s, gen 24.3 t/s; but still slower than F16 KV UB=256 (-16% prefill, -14% gen, +30% total time)
3. **Q8_0 KV UB=4096 degrades everywhere** — prefill -30~40% at p4K+, gen -7~33%, 256K Vulkan crash at ~160K tokens
4. **Even the best Q8_0 config (ub=1024) loses to F16 ub=256 at p64K+** — prefill -2~13%, gen -7~9%
5. **Conclusion: F16 KV UB=256 remains optimal for 35B MoE.** Vulkan FA dequantization overhead exceeds the bandwidth savings from Q8_0 compression; MoE's sparse KV cache (3B active params) means limited bandwidth to save. Q8_0 KV only benefits short-context prefill (≤32K); at 256K context even UB=512 (the only viable Q8_0 config) is still 30% slower than F16 KV UB=256.

</details>



### 27B Dense Q8 (Q8_K_XL, removed) — Not Recommended

**F16 KV cache (ub=256):**

| Prompt Size | Gen Speed | Prefill Speed | TTFT |
|-------------|-----------|---------------|------|
| 128 tokens | 13.1 t/s | 115.2 t/s | 1.1s |
| 4K tokens | 11.9 t/s | 133.6 t/s | 30.6s |
| 32K tokens | 11.7 t/s | 174.6 t/s | 187.7s |
| 64K tokens | 11.7 t/s | 110.0 t/s | 595.6s |
| 128K tokens | 10.0 t/s | 49.8 t/s | 2633.1s |
| 256K tokens | — | — | ❌ timeout 7200s |

<details>
<summary><b>Q8_0 KV Cache + UB Sweep Results</b></summary>

Q8_0 KV cache tested across 4 UB values (256–4096), compared against F16 KV UB=256 baseline. UB≥2048 crashes at 128K+ context.

**Prefill speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 | Q8_0 ub=4096 |
|--------|-----------|-------------|-------------|--------------|--------------|--------------|
| p128 | 115.2 | 115.8 | 61.1 | 61.0 | — | — |
| p4K | 133.6 | 130.1 | 125.2 | 126.3 | — | — |
| p32K | 174.6 | 172.3 | **204.9** | **211.9** | — | — |
| p64K | 110.0 | 151.1 | **264.3** | 261.8 | — | — |
| p128K | 49.8 | 115.8 | **185.1** | 115.3 | 116.9 | ❌ crash |
| p256K | ❌ | 80.8 | **138.6** | 136.7 | ❌ crash | ❌ crash |

**Gen speed (t/s):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 | Q8_0 ub=4096 |
|--------|-----------|-------------|-------------|--------------|--------------|--------------|
| p128 | **13.1** | 12.5 | 12.0 | 12.5 | — | — |
| p4K | **11.9** | 12.7 | 13.0 | 12.7 | — | — |
| p32K | **11.7** | 11.7 | 11.1 | 11.1 | — | — |
| p64K | **11.7** | 10.9 | 10.4 | 10.0 | — | — |
| p128K | **10.0** | 9.5 | 9.3 | 8.9 | 9.0 | ❌ crash |
| p256K | ❌ | **7.2** | 6.8 | 6.7 | ❌ crash | ❌ crash |

**TTFT (seconds):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|-------------|--------------|--------------|
| p128 | 1.1s | 1.1s | 2.1s | 2.1s | — |
| p4K | 30.6s | 31.5s | 32.7s | 32.4s | — |
| p32K | 187.7s | 190.2s | **160.0s** | **154.6s** | — |
| p64K | 595.6s | 433.8s | **248.0s** | 250.4s | — |
| p128K | 2633.1s | 1132s | **708.3s** | 1136.9s | 1121.2s |
| p256K | ❌ | 2994.1s | **1891.4s** | 1917.1s | ❌ crash |

**Total elapsed time (seconds):**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128K | 2716 | 1231 | **794** | 1224 |
| p256K | ❌ | 3164 | **1983** | 2040 |

**Findings:**

1. **UB=512 is the optimal choice for 27B Dense Q8_0 KV** — fastest TTFT and total time at p64K–p256K; prefill +75% vs UB=256 at p64K
2. **UB=1024 outperforms UB=256 only at p256K prefill** (+69%), but underperforms UB=512 at p128K/p256K TTFT by 38–60%
3. **Q8_0 KV makes 256K context viable** — F16 KV times out at 256K; Q8_0 KV completes in 33–53 min
4. **Q8_0 KV dramatically improves long-context prefill** — p128K: +132% vs F16; p64K: +37% vs F16
5. **UB≥2048 Vulkan crash** — UB=2048 p256K crash, UB=4096 p128K crash; 27B Dense has tighter VRAM headroom than 35B MoE
6. **UB=512 p256K total time 33 min vs UB=256's 53 min** — saves 20 minutes per 256K request

</details>

> **Removed from active roster.** Gen speed only 7–13 t/s (vs Q6 ~17 t/s, Q4 ~21 t/s). Q8_0 KV enables 256K context and massively improves long-context prefill, but gen is still slow. Use Q6 or Q4 instead.

---

## Optimization Parameters

### Key Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Service = server-level, INI = model-level | Clean separation; change model params without touching service file |
| Unified 256K context | `-c` only pre-allocates KV cache; no performance impact; one config for all prompt lengths |
| Per-quant differentiated ub | Higher quant = larger weights = less VRAM headroom = smaller ub for stability |
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
| 35B MoE: max context | 256K (ub=256) | ub≥2048 causes Vulkan crash at 128K+ |
| 27B Dense: max context | 256K (Q8_0 KV, ub=512) | F16 KV 256K times out; Q8_0 KV ub=512 viable at 256K (33 min); ub≥2048 crashes |
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

[Qwen3.6-27B-UD-Q6_K_XL]
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
| llama.cpp | b9210 (commit c3f95c1f0, Vulkan backend) |
| Build options | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` (+ BLAS/OpenMP/LTO/NATIVE) |
| Vulkan runtime | 1.4.341 |
| API protocol | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |

**Path layout on inference box:**

| Item | Path |
|------|------|
| Model files + preset INI | `$HOME/model/` |
| llama-server binary | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Router preset | `$HOME/model/router-preset.ini` |

### Model Inventory

Router Mode serves all models from `$HOME/model/`. Only one is loaded at a time (`--models-max 1`), switching via LRU on client request. Each model has an **alias** for short-name routing. 27B Q8 is currently removed from the active roster due to poor usability (slow generation, long prefill at extended contexts).

| Model | File | Alias | Quant | Arch | Size | Active Params |
|-------|------|-------|-------|------|------|---------------|
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | **358** | Q8_K_XL | **MoE** | ~37 GB | 3B |
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
- [ ] Cloud: `curl http://127.0.0.1:8080/v1/models` returns 3 models with aliases
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

*Tested on FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9210 Vulkan · 2026-05-22*
