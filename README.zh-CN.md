# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 暴露推理 API。

## 架构

```
┌─────────────────┐      HTTPS (443)      ┌──────────────────┐
│   客户端         │ ────────────────────▶ │  云端 Nginx      │
│  (任意设备)     │                       │  {your_domain}   │
└─────────────────┘                       └────────┬─────────┘
                                                  │
                                      proxy_pass 127.0.0.1:8080
                                                  │
┌─────────────────┐      SSH 反向隧道              │
│   推理机         │ ◀─────────────────────────────┘
│  Ubuntu 26.04   │  127.0.0.1:8080 ←→ 127.0.0.1:12345
│  AMD AI Max+395 │
│  128 GB RAM     │
└─────────────────┘
```

**核心设计原则：**
- llama.cpp 仅绑定 `127.0.0.1:12345`，不暴露任何网络访问
- 云端仅运行 **Nginx**（443 端口），不运行任何应用程序
- SSH 反向隧道实现 NAT 穿透（家庭网络 → 云端）
- OpenAI 兼容 API：`https://{your_domain}/v1/`
- **Router Mode** + per-model preset INI，自动 LRU 模型切换
- **别名短名**（358/278/276/274）便捷路由
- **参数分离**：service 文件仅含服务级参数，INI 仅含模型级参数

---

## 硬件

| 组件 | 规格 |
|------|------|
| 机型 | FEVM faex1 迷你主机 |
| APU | AMD Ryzen AI Max+ 395 (16C/32T) |
| 内存 | 128 GB LPDDR5X (256-bit, 统一内存) |
| 存储 | 1 TB NVMe SSD |
| 核显 | Radeon 8060S (RDNA 3.5, 40 CU, 2040 MHz) |
| GTT (GPU 可访问内存) | 120 GB (内核参数 `amdgpu.gttsize=122880`) |

**内存带宽：** 256-bit × 8000 MT/s ÷ 8 = **256 GB/s** 理论值，~200 GB/s 实际值。Dense 模型受内存带宽限制。

---

## 软件

| 组件 | 版本 / 详情 |
|------|------------|
| 推理机系统 | Ubuntu 26.04 LTS |
| 云端系统 | Ubuntu 24.04.4 LTS |
| llama.cpp | b9210 (commit c3f95c1f0, Vulkan 后端) |
| Vulkan 运行时 | 1.4.341 |
| API 协议 | OpenAI 兼容 (`/v1/chat/completions`, `/v1/models`) |

**推理机路径布局：**

| 项目 | 路径 |
|------|------|
| 模型文件 + preset INI | `$HOME/model/` |
| llama-server 二进制 | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Router preset | `$HOME/model/router-preset.ini` |

---

## 模型清单

Router Mode 从 `$HOME/model/` 提供所有模型服务。一次只加载一个模型（`--models-max 1`），通过 LRU 按需切换。每个模型配置了 **alias 别名** 便于 API 路由。

| 模型 | 文件名 | 别名 | 量化 | 架构 | 大小 | 激活参数 |
|------|--------|------|------|------|------|---------|
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | **358** | Q8_K_XL | **MoE** | ~37 GB | 3B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | **278** | Q8_K_XL | Dense | ~34 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | **276** | Q6_K_XL | Dense | ~25 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | **274** | Q4_K_XL | Dense | ~17 GB | 27B |

> **别名命名规则：** 3 位数字 = 模型大小 + 量化等级。如 `358` = 35B Q8，`274` = 27B Q4。
> API 请求的 `model` 字段使用别名或完整文件名均可。

---

## 云端部署

### 1. Nginx 配置

**文件：** `/etc/nginx/sites-available/default`

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

    # LLM API 端点（OpenAI 兼容）
    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;

        # SSE 流式响应支持
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }

    # 健康检查
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**应用：** `sudo nginx -t && sudo systemctl reload nginx`

### 2. SSL 配置

**文件：** `/etc/nginx/snippets/snakeoil.conf`

```nginx
ssl_certificate /root/cert.nginx/{your_domain}.pem;
ssl_certificate_key /root/cert.nginx/{your_domain}.key;

ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers HIGH:!aNULL:!MD5;
ssl_prefer_server_ciphers on;
```

### 3. 云端 SSH 服务端

**文件：** `/etc/ssh/sshd_config`

```sshd_config
AllowTcpForwarding yes
ClientAliveInterval 60
ClientAliveCountMax 3
# GatewayPorts no   (默认 — 保持隧道仅绑定 127.0.0.1)
```

**应用：** `sudo systemctl restart ssh`

---

## SSH 反向隧道

### systemd 服务（生产环境）

**文件：** `~/.config/systemd/user/llm-tunnel.service`（用户级，无需 sudo）

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

**隧道端口：** `-R 8080:127.0.0.1:12345`（API）

```bash
mkdir -p ~/.config/systemd/user
# 创建 service 文件后：
systemctl --user daemon-reload
systemctl --user enable llm-tunnel
systemctl --user start llm-tunnel
loginctl enable-linger   # 防止登出后服务终止
```

### SSH 密钥设置（免密登录）

在推理机上执行：
```bash
ssh-keygen -t ed25519 -C "llm-tunnel@faex1"
ssh-copy-id root@{your_server_ip}
```

---

## 推理服务（Router Mode）

### 参数分离原则

| 范围 | 位置 | 示例 |
|------|------|------|
| **服务级** | `llm-router.service` ExecStart | `--host`, `--port`, `--api-key`, `--models-dir`, `--models-max`, `--models-preset`, `--sleep-idle-seconds`, `--timeout` |
| **模型级** | `router-preset.ini` 每模型 section | `n-gpu-layers`, `ctx-size`, `ubatch-size`, `threads`, `alias`, `spec-type`, `mlock`, `numa`, ... |

> 模型参数**仅在 INI 中定义**，不在 service 文件中重复。

### systemd 服务

**文件：** `~/.config/systemd/user/llm-router.service`（用户级，无需 sudo）

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
loginctl enable-linger   # 防止登出后服务终止
```

### Preset INI（模型级参数）

**文件：** `~/model/router-preset.ini`

每个模型 section 仅含**模型级参数**。服务级设置（host、port、api-key、models-dir 等）在 service 文件中。

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
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
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

**参数设计理由：**

| 参数 | 值 | 理由 |
|------|-----|------|
| `ctx-size = 262144` | 全部模型 | 统一 256K；-c 不影响性能，只预分配 KV cache |
| `batch-size = 4096` | 全部模型 | 最优调度粒度；b 必须被 ub 整除 |
| `ubatch-size` | 256/256/512/1024 | 按量化等级分配 VRAM：量化越高 → ub 越小 → 256K 更稳定 |
| `threads = 8` | 全部模型 | 全 GPU 卸载下 t=8 vs t=16 差异 < 2%，t=8 更低温 |
| `alias` | 358/278/276/274 | 短名路由，无需符号链接 |

**修改模型参数：** 编辑 INI 文件 → `systemctl --user restart llm-router`

> ⚠️ **27B Dense 模型尚未在 256K 上下文下测试。** Q8 权重 ~34 GB + KV cache 可能 VRAM 不足，建议先从 Q4（最小）试水。

### 模型切换

客户端在请求中指定 `model` 字段即可自动切换（LRU，冷切换耗时 8–17 秒）。**别名和完整文件名均可**：

```bash
# 使用别名（推荐）
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "358", ...}'

# 使用完整文件名（也可以）
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "Qwen3.6-35B-A3B-UD-Q8_K_XL", ...}'
```

**QClaw 集成：**

| 命令 | 模型 |
|------|------|
| `/model 358` | 35B-A3B Q8 (MoE, 最快) |
| `/model 278` | 27B Q8 (Dense, 最高质量) |
| `/model 276` | 27B Q6 (Dense, 平衡) |
| `/model 274` | 27B Q4 (Dense, 最省资源) |

---

## 性能基准

### 35B-A3B (MoE, 256K 已验证)

| 场景 | 配置 | Gen 速度 | Prefill 速度 | MTP 命中率 |
|------|------|----------|-------------|-----------|
| 短 prompt | `-c 262144 -b 4096 -ub 256 -t 8` | ~72 t/s | ~114 t/s | ~100% |
| 256K 长上下文 | `-c 262144 -b 4096 -ub 256 -t 8` | 28–31 t/s | 260–285 t/s | 54–73% |

> 短 prompt 速度为冷启动（模型加载后首次请求）测量。MTP 命中率受 prompt 内容影响。

### 27B (Dense, 128K 上下文)

| 量化 | Gen 速度 | MTP 命中率 |
|------|----------|-----------|
| Q4_K_XL | ~21 t/s | ~80% |
| Q6_K_XL | ~15 t/s | ~80% |
| Q8_K_XL | ~11 t/s | ~76% |

> 27B 速度在 128K 上下文下测量。256K 上下文性能待测。

### 256K 上下文：ub 是关键参数

`ub`（微批次大小）控制 GPU 单次前向传播的 VRAM 峰值。是 256K 稳定性的关键变量（35B-A3B MoE 实测）：

| ub | 256K 稳定性 | Prefill (t/s) | Gen (t/s) | MTP |
|:--:|:--------------:|:-------------:|:---------:|:---:|
| 256 | ✅ 稳定 | 260 | 31.3 | 73.1% |
| 512 | ✅ 稳定 | 268 | 29.7 | 67.6% |
| 1024 | ✅ 稳定 | 136 | 30.8 | 75.8% |
| 2048+ | ❌ Vulkan 崩溃 | — | — | — |

**崩溃边界：** ub=2048 在 ~155K tokens 崩溃，ub=4096 在 ~86K，ub=8192 在 ~49K。根因：大 ub 单次前向传播 VRAM 峰值超 Vulkan 驱动承受范围。

**按量化等级分配 ub 的策略：**
- Q8 → ub=256（权重最大，VRAM 余量最小）
- Q6 → ub=512（中等余量）
- Q4 → ub=1024（权重最小，VRAM 余量最大）

---

## 关键决策

| 决策 | 理由 |
|------|------|
| Service = 服务级，INI = 模型级 | 层次清晰，改模型参数不碰 service 文件 |
| 统一 256K 上下文 | -c 不影响性能，一套配置覆盖所有 prompt 长度 |
| 按量化等级差异化 ub | 量化越高权重越大，VRAM 余量越小，需更小 ub 保证 256K 稳定 |
| 不使用 `--cache-ram` | 统一内存上 pinned alloc 失败且慢 4.6%；默认 prompt cache 更优 |
| `--reasoning-budget 8192` | 防止思考 token 耗尽 KV cache/VRAM，无性能损失 |
| `-np 1` 强制 | MTP 不支持多 slot，5 并发速度降 75% |
| `--spec-draft-n-max 3` | 4 比 3 慢 20.6% |
| 全部模型 `-t 8` | 全 GPU 卸载下 t=8 vs t=16 无实质差异，t=8 更低温 |
| 不加 `--no-mmap` | 无收益，--mmap（默认）+ --mlock 是最佳组合 |
| `-a Qwen3.6` | b9210 API 要求响应中有 model 字段 |
| alias 短名 | 无需符号链接；别名和文件名均可路由 |

---

## 使用约束

| 限制 | 值 | 原因 |
|------|---|------|
| 最大并发槽位 | 1 (`-np 1`) | **强制** — MTP 不支持多 slot |
| 最大上下文 | 256K (ub=256) | ub≥2048 在 128K+ 导致 Vulkan 崩溃 |
| 避免 thinking 模式 | 不要开启 `thinking=1` | 降低 MTP 命中率 |
| 避免并发 | 一次一个请求 | 并发 → 速度损失 75% |
| 禁止 `--cache-ram` | 不要加 | 统一内存上有害 |
| b 必须被 ub 整除 | `n_batch % n_ubatch == 0` | llama.cpp 硬性要求 |
| 27B Dense 256K | 尚未验证 | 先从 Q4 测试 VRAM 充足性 |

---

## 验证清单

- [ ] 云端 Nginx 配置已更新（含 `/v1/` 和 `/health` 端点）
- [ ] 云端 SSL 证书已配置
- [ ] 云端 `sshd_config` 允许 TCP 转发和 keepalive
- [ ] 推理机已配置免密登录云端
- [ ] `llm-tunnel.service` 已创建并 **运行中**
- [ ] `llm-router.service` 已创建并 **运行中**（仅服务级参数）
- [ ] `~/model/router-preset.ini` 配置正确（模型级参数 + alias）
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回 4 个模型 + aliases
- [ ] 外网：`curl https://{your_domain}/health` 返回 `OK`
- [ ] 别名路由：`curl -d '{"model":"358",...}'` 路由到 35B-A3B Q8

**快速冒烟测试：**
```bash
# 使用别名
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

*测试环境：FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9210 Vulkan · 2026-05-19*
