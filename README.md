# Strix Halo LLM Deploy — Qwen3.6

Deploy Qwen3.6 large language models on AMD Ryzen AI Max+ 395 (Strix Halo) with llama.cpp + Vulkan, and expose the inference API to the internet via SSH reverse tunnel + Nginx HTTPS.

## Architecture

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

---

## Hardware

| Component | Specification |
|-----------|--------------|
| Machine | FEVM faex1 mini PC |
| APU | AMD Ryzen AI Max+ 395 (16C/32T) |
| Memory | 128 GB LPDDR5X (256-bit) |
| Storage | 1 TB NVMe SSD |
| iGPU | Radeon 8060S (RDNA 3.5, 40 CU, 2040 MHz) |
| GTT (GPU-accessible RAM) | 120 GB (kernel param `amdgpu.gttsize=122880`) |

**Memory bandwidth analysis:**
- Theoretical: 256-bit × 8533 MT/s ÷ 8 = **273 GB/s**
- Practical: ~200 GB/s (after system overhead)
- **Dense models are memory-bandwidth bound** — thread count has minimal impact

---

## Software

| Component | Version / Details |
|-----------|-------------------|
| Inference OS | Ubuntu 26.04 LTS |
| Cloud OS | Ubuntu 24.04.4 LTS |
| llama.cpp | Vulkan backend (`GGML_USE_VULKAN=on`) |
| Vulkan runtime | 1.4.341 |
| API protocol | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |

**Path layout on inference box:**

| Item | Path |
|------|------|
| Model files | `$HOME/model/` |
| llama.cpp source | `$HOME/llama/llama.cpp/` |
| llama-server binary | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Service log | `$HOME/llama-server.log` |

---

## Model Inventory

> Only one model runs at a time (manual switch; auto-switch tool planned).

| Model | File | Quant | Arch | Size | Active Params |
|-------|------|-------|------|------|---------------|
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | Q8_K_XL | **MoE** | ~37 GB | 3B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | Q4_K_XL | Dense | ~17 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | Q6_K_XL | Dense | ~25 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | Q8_K_XL | Dense | ~34 GB | 27B |

---

## Cloud Deployment

### 1. Nginx Configuration

**File:** `/etc/nginx/sites-available/default`

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;

    include snippets/snakeoil.conf;

    root /var/www/html;
    index index.html index.htm index.nginx-debian.html;
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

        # Long timeouts (LLM inference is slow)
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

**Apply:**
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 2. SSL Configuration

**File:** `/etc/nginx/snippets/snakeoil.conf`

```nginx
ssl_certificate /root/cert.nginx/{your_domain}.pem;
ssl_certificate_key /root/cert.nginx/{your_domain}.key;

ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers HIGH:!aNULL:!MD5;
ssl_prefer_server_ciphers on;
```

> Comment out the default snakeoil self-signed certs and use your real certificates.

### 3. Cloud SSH Server

**File:** `/etc/ssh/sshd_config`

```sshd_config
AllowTcpForwarding yes
ClientAliveInterval 60
ClientAliveCountMax 3
# GatewayPorts no   (default — keep tunnel on 127.0.0.1 only)
```

**Apply:**
```bash
sudo systemctl restart ssh
sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|gatewayports"
```

---

## SSH Reverse Tunnel

### Inference Box → Cloud (Forward Tunnel for API)

The inference box establishes an SSH reverse tunnel so the cloud Nginx can reach `localhost:12345`:

```bash
ssh -R 8080:127.0.0.1:12345 \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -N root@{your_server_ip}
```

### systemd Service (Production)

**File:** `/etc/systemd/system/llm-tunnel.service`

```ini
[Unit]
Description=LLM SSH Reverse Tunnel
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={account_name}
ExecStart=/usr/bin/ssh \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o ConnectTimeout=10 \
    -R 8080:127.0.0.1:12345 \
    -N \
    root@{your_server_ip}
Restart=always
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable llm-tunnel
sudo systemctl start llm-tunnel
```

### SSH Key Setup (Passwordless)

On the inference box:
```bash
ssh-keygen -t ed25519 -C "llm-tunnel@faex1"
ssh-copy-id root@{your_server_ip}
ssh root@{your_server_ip} "echo OK"   # verify
```

---

## Inference Service (llama.cpp)

### 128K Speed-Optimized Configuration

**Common base parameters** — only the model file differs:

```bash
$HOME/llama/llama.cpp/build/bin/llama-server \
    -m $HOME/model/<MODEL_FILE>.gguf \
    -ngl 99 -c 131072 -fa on -np 1 \
    -t 12 -b 8192 -ub 8192 \
    --spec-type draft-mtp --spec-draft-n-max 3 \
    --cache-ram 49152 \
    --mlock --numa distribute \
    --reasoning-budget 8192 \
    --timeout 3600 \
    --host 127.0.0.1 --port 12345 \
    --api-key {your_api_key}
```

**Benchmarks (3-round average, 128K context):**

| Model | File | Arch | Speed (t/s) | Detail |
|-------|------|------|:-----------:|--------|
| **35B-A3B Q8** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | MoE | **48.29** | 48.64, 47.11, 49.11 |
| **27B Q4** | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | Dense | **21.22** | 20.35, 21.88, 21.43 |
| **27B Q6** | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | Dense | **15.09** | 15.86, 14.69, 14.72 |
| **27B Q8** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | Dense | **11.32** | 11.46, 11.16, 11.35 |

### 256K Ultra-Long Context (35B-A3B only, no MTP)

```bash
$HOME/llama/llama.cpp/build/bin/llama-server \
    -m $HOME/model/Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf \
    -ngl 99 -c 262144 -fa on -np 1 \
    -t 6 -b 4096 -ub 512 \
    --cache-ram 24000 \
    --reasoning-budget 8192 \
    --timeout 3600 \
    --host 127.0.0.1 --port 12345 \
    --api-key {your_api_key}
```

- Speed: **~0.67 t/s** (at 213K tokens prompt) — very slow, use only when 128K context is insufficient
- MTP **hurts** at 256K (0.59 t/s vs 0.67 t/s) — large batch crashes Vulkan, small batch gains nothing

### systemd User Service (Inference)

**File:** `$HOME/.config/systemd/user/llm-inference.service`

```ini
[Unit]
Description=LLM Inference Service (Qwen3.6-35B-A3B)
After=network.target

[Service]
Type=simple
ExecStart=$HOME/llama/llama.cpp/build/bin/llama-server \
    -m $HOME/model/Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf \
    -ngl 99 -c 131072 -fa on -np 1 \
    -t 12 -b 8192 -ub 8192 \
    --spec-type draft-mtp --spec-draft-n-max 3 \
    --cache-ram 49152 \
    --mlock --numa distribute \
    --reasoning-budget 8192 \
    --timeout 3600 \
    --host 127.0.0.1 --port 12345 \
    --api-key {your_api_key}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable llm-inference
systemctl --user start llm-inference
loginctl enable-linger   # survive logout
```

**Operations:**
```bash
systemctl --user status llm-inference
systemctl --user restart llm-inference
journalctl --user -u llm-inference -f
```

---

## Parameter Tuning Findings

All tests below were conducted on the 35B-A3B MoE model with 128K context unless noted.

### Thread Count (`-t`)

| `-t` | Speed (t/s) | vs `-t 12` |
|:----:|:-----------:|:----------:|
| 6 | 61.27 | -6.5% |
| 10 | 60.98 | -6.0% |
| **12** | **65.24** | **baseline** |
| 16 | 58.62 | -10.2% |
| 24 | 61.0 | -6.5% |

> Inverted-U curve: `-t 12` (37.5% of 32 threads) is the sweet spot. More threads introduce synchronization overhead.

### MTP Draft Depth (`--spec-draft-n-max`)

| Value | Speed (t/s) | vs 3 |
|:-----:|:-----------:|:----:|
| 2 | 62.68 | -4% |
| **3** | **65.24** | **baseline** |
| 4 | 51.80 | -20.6% |

> Too many speculative drafts hurt — the rejection cost outweighs the acceptance gain.

### MTP Impact

| Config | Speed (t/s) | vs No MTP |
|--------|:-----------:|:---------:|
| No MTP | 47.72 | baseline |
| MTP (draft-n-max=3) | 65.24 | **+36.7%** |

> MTP is the single biggest speedup. Always enable it for 128K context.

### Other Parameters (35B-A3B, 128K)

| Parameter Change | Speed Impact | Keep? |
|-----------------|:------------:|:-----:|
| `-c 262144` (vs 131072) | -9.5% | Only when needed |
| Remove `--numa distribute` | -6.4% | ✅ Keep |
| Remove `--mlock` | -9.7% | ✅ Keep |
| `-fa off` | -10.6% | ✅ Keep |
| `-b 4096` (vs 8192) | -6.9% | ❌ 8192 is optimal |
| `-b 16384` (vs 8192) | -9.8% | ❌ Too large |
| `--no-mmap` | ~0% | ❌ No measurable difference |
| 5 concurrent requests | -74.7% (avg 16.5 t/s) | ❌ Avoid concurrency |

### Dense Model Quantization Comparison

| Quant | Speed (t/s) | vs Q8 | Model Size |
|:-----:|:-----------:|:-----:|:----------:|
| Q4_K_XL | 21.22 | +87.6% | ~17 GB |
| Q6_K_XL | 15.09 | +33.2% | ~25 GB |
| Q8_K_XL | 11.32 | baseline | ~34 GB |

> Speed scales almost linearly with model size — memory bandwidth is the bottleneck for Dense models.

### 256K Context Findings

| Scenario | Result |
|----------|--------|
| Large batch (`-b 8192 -ub 8192`) + 256K | **Vulkan DeviceLostError crash** — unusable |
| Small batch (`-b 4096 -ub 512`) + 256K, no MTP | Works at ~0.67 t/s (213K prompt) |
| MTP + 256K | **Slower** than no-MTP (0.59 vs 0.67 t/s) — not viable |
| `--cache-ram 49152` + 256K | **Vulkan crash** — too much VRAM pressure |

**Conclusion:** 256K context is only viable with 35B-A3B + small batch + no MTP, and is extremely slow. Use 128K whenever possible.

---

## Model Selection Guide

```
Need 256K context?
├─ Yes → 35B-A3B (256K, ~0.67 t/s, no MTP)
│         ⚠ Only when 128K is truly insufficient
└─ No → Need fastest speed?
    ├─ Yes → 35B-A3B (128K, ~48 t/s) ✅ Recommended
    └─ No → Dense model needed?
        ├─ 27B Q4 → 21 t/s (fastest Dense, lowest quality)
        ├─ 27B Q6 → 15 t/s (balanced)
        └─ 27B Q8 → 11 t/s (best Dense quality)
```

**For most use cases, 35B-A3B at 128K is the clear winner** — MoE architecture activates only 3B of 35B parameters, delivering 4.3× the speed of 27B Dense Q8 with comparable quality.

---

## Cloud vs LAN Performance

| Metric | LAN | Cloud (HTTPS) | Overhead |
|--------|:---:|:-------------:|:--------:|
| Short generation (50 tokens) | ~58 t/s | ~56 t/s | ~3% |
| Long generation (512 tokens) | ~52 t/s | ~48.5 t/s | ~5% |
| Server-side eval | ~71 t/s | ~71 t/s | 0% |

- Network overhead is **3–5%** — negligible
- Speed variation between requests is dominated by **MTP acceptance rate**, not network latency
- Use `"stream": true` for best perceived responsiveness (SSE already configured in Nginx)

---

## 128 GB RAM Allocation

| Purpose | Size | Notes |
|---------|------|-------|
| OS + system | 8 GB | Base runtime |
| Model weights | 37 GB (35B) or 17 GB (27B Q4) | Loaded into GPU-accessible memory |
| KV Cache | 48 GB (`--cache-ram 49152`) | Context cache for 128K |
| System buffer/cache | ~35 GB | File cache, remaining headroom |

> For 256K context, reduce `--cache-ram` to 24000 (24 GB) and use smaller batch sizes.

---

## Usage Limits

| Limit | Value | Reason |
|-------|-------|--------|
| Max concurrent slots | 1 (`-np 1`) | MTP does not support multi-slot |
| Max context | 128K (recommended) | 256K is extremely slow |
| Avoid thinking mode | Don't enable `thinking=1` | Lowers MTP acceptance rate |
| Avoid concurrency | 1 request at a time | 5 concurrent → 75% speed loss |

---

## Verification Checklist

- [ ] Cloud Nginx config updated (with `/v1/` and `/health` endpoints)
- [ ] Cloud SSL certificates configured in `snippets/snakeoil.conf`
- [ ] Cloud `sshd_config` allows TCP forwarding and keepalive
- [ ] Inference box has SSH key for passwordless login to cloud
- [ ] `llm-tunnel.service` created and **active** on inference box
- [ ] `llm-inference.service` created and **active** on inference box
- [ ] Cloud: `curl http://127.0.0.1:8080/v1/models` returns model list
- [ ] External: `curl https://{your_domain}/health` returns `OK`
- [ ] External: chat completion works with valid API key

**Quick smoke test:**
```bash
curl https://{your_domain}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{
    "model": "Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50,
    "stream": true
  }'
```

---

## Key Takeaways

1. **MoE dominates** — 35B-A3B (3B active) is 4.3× faster than 27B Dense Q8
2. **MTP is critical** — +36.7% speedup with `--spec-draft-n-max 3`
3. **`-t 12` is optimal** — not more threads (inverted-U curve)
4. **Memory bandwidth is the bottleneck** for Dense models — quantization level directly determines speed
5. **256K context is a last resort** — 128K with MTP is the sweet spot
6. **Network overhead is negligible** — 3–5% via HTTPS, use streaming for best UX
7. **No concurrency** — single-slot MTP, avoid concurrent requests

---

*Tested on FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp Vulkan · 2026-05-18*
