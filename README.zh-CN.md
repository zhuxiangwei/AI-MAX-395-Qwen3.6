# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 暴露推理 API。

---

## 性能基准

所有基准测试均在 FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9210 Vulkan) 上完成。

### 35B-A3B MoE (Q8_K_XL, 别名 `358`)

**主力模型——生成速度最快，256K 上下文稳定运行。** ✅ *测试完成。*

| Prompt 大小 | Gen 速度 | Prefill 速度 | TTFT |
|-------------|----------|-------------|------|
| 128 tokens | 54.4 t/s | 340.2 t/s | 0.37s |
| 4K tokens | 56.6 t/s | 391.3 t/s | 10.5s |
| 32K tokens | 46.9 t/s | 520.1 t/s | 63.0s |
| 64K tokens | 45.5 t/s | 448.1 t/s | 146.2s |
| 128K tokens | 36.5 t/s | 344.6 t/s | 380.4s |
| 256K tokens | 28.4 t/s | 238.2 t/s | 1015.0s |

> 配置：`-c 262144 -b 4096 -ub 256 -t 8`，F16 KV cache，Thinking 已开启（`reasoning-budget=8192`）。Gen 速度含 thinking tokens（真实使用场景）。MoE 每个 token 仅激活 35B 中的 3B 参数 → 生成速度最快。

<details>
<summary><b>Q8_0 KV Cache + UB 扫描结果</b></summary>

Q8_0 KV cache 在 4 种 UB 值（512–4096）下测试，对比 F16 KV UB=256 基线。

**Prefill 速度 (t/s)：**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 | Q8_0 ub=4096 |
|--------|-----------|-------------|--------------|--------------|--------------|
| p128 | 340.2 | 364.2 | 297.9 | 338.2 | 343.6 |
| p4K | 391.3 | 468.8 | **480.0** | 450.0 | 295.4 |
| p32K | 520.1 | 544.9 | **589.0** | 576.1 | 384.4 |
| p64K | 448.1 | 421.3 | **450.8** | 440.4 | 327.5 |
| p128K | **344.6** | 287.5 | 298.7 | 295.2 | 241.4 |
| p256K | **238.2** | — | — | — | ❌ 崩溃 |

**Gen 速度 (t/s)：**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 | Q8_0 ub=4096 |
|--------|-----------|-------------|--------------|--------------|--------------|
| p128 | **54.4** | 51.6 | 53.5 | 52.5 | 53.9 |
| p4K | **56.6** | 51.3 | 50.2 | 52.7 | 47.7 |
| p32K | **46.9** | 45.3 | 46.1 | 43.9 | 46.5 |
| p64K | **45.5** | 43.7 | 40.7 | 41.2 | 42.4 |
| p128K | **36.5** | 34.0 | 33.3 | 33.3 | 33.9 |
| p256K | **28.4** | — | — | — | ❌ 崩溃 |

**结论：**

1. **Q8_0 KV UB=1024 是 Q8_0 配置中的最优**——p4K–p128K prefill 最快，gen 和 TTFT 接近最优
2. **Q8_0 KV UB=4096 全面劣化**——p4K+ prefill 慢 30~40%，gen 慢 7~33%，256K 在 ~160K tokens 处 Vulkan 崩溃
3. **MTP 接受率随 UB 增大而下降**——71.3% (ub=256) → 65.6% (ub=4096)
4. **即使最优 Q8_0 配置 (ub=1024) 在 p64K+ 仍不如 F16 ub=256**——prefill -2~13%，gen -7~9%
5. **结论：35B MoE 维持 F16 KV UB=256。** Vulkan FA 反量化开销超过 Q8_0 压缩节省的带宽；MoE 稀疏 KV cache（3B 激活参数）意味着可节省的带宽本就有限

</details>



### 27B Dense Q8 (Q8_K_XL, 已移除) — 不推荐

| Prompt 大小 | Gen 速度 | Prefill 速度 | TTFT | KV Cache |
|-------------|----------|-------------|------|----------|
| 128 tokens | 13.1 t/s | 115.2 t/s | 1.1s | F16 |
| 4K tokens | 11.9 t/s | 133.6 t/s | 30.6s | F16 |
| 32K tokens | 11.7 t/s | 174.6 t/s | 187.7s | F16 |
| 64K tokens | 11.7 t/s | 110.0 t/s | 595.6s | F16 |
| 128K tokens | 10.0 t/s | 49.8 t/s | 2633.1s | F16 |
| 128K tokens | 9.5 t/s | 115.8 t/s | 1131.9s | Q8_0 |

> **已从活跃名单移除。** Gen 速度仅 11–13 t/s（Q6 ~17 t/s，Q4 ~21 t/s）；256K 不可行（F16 KV Vulkan 崩溃，Q8_0 KV 超时）；Q8_0 KV 改善长上下文 prefill（p128K +132%）但 gen 仍仅 ~9.5 t/s。建议使用 Q6 或 Q4。

---

## 优化参数

### 关键决策及理由

| 决策 | 理由 |
|------|------|
| Service = 服务级，INI = 模型级 | 层次清晰，改模型参数不碰 service 文件 |
| 统一 256K 上下文 | -c 只预分配 KV cache，不影响性能；一套配置覆盖所有 prompt 长度 |
| 按量化等级差异化 ub | 量化越高权重越大，VRAM 余量越小，需更小 ub 保证稳定性 |
| 不使用 `--cache-ram` | 统一内存上 pinned alloc 失败且慢 4.6%；默认 prompt cache 更优 |
| `--reasoning-budget 8192` | 防止思考 token 耗尽 KV cache/VRAM，无性能损失 |
| `-np 1` 强制 | MTP 不支持多 slot，5 并发速度降 75% |
| `--spec-draft-n-max 3` | 4 比 3 慢 20.6% |
| 全部模型 `-t 8` | 全 GPU 卸载下 t=8 vs t=16 无实质差异，t=8 更低温 |
| 不加 `--no-mmap` | 无收益，`--mmap`（默认）+ `--mlock` 是最佳组合 |
| `-a Qwen3.6` | b9210 API 要求 model 字段 |
| alias 短名路由 | 无需符号链接；别名和文件名均可路由 |

### 使用约束

| 约束 | 值 | 原因 |
|------|---|------|
| 最大并发槽位 | 1 (`-np 1`) | **强制** — MTP 不支持多 slot |
| 35B MoE 最大上下文 | 256K (ub=256) | ub≥2048 在 128K+ 时 Vulkan 崩溃 |
| 27B Dense 最大上下文 | ~64K–96K | 256K F16 KV 不可行；Dense KV cache 太大，Vulkan 崩溃 |
| Thinking 模式 | 已开启（`reasoning-budget=8192`） | Budget 上限防止思考 token 失控增长；无性能损失 |
| 避免并发 | 一次一个请求 | 并发 → 速度损失 75% |
| 禁止 `--cache-ram` | 不要加 | 统一内存上有害 |
| b 必须被 ub 整除 | `n_batch % n_ubatch == 0` | llama.cpp 硬性要求 |

### 参数分离原则

| 范围 | 位置 | 示例 |
|------|------|------|
| **服务级** | `llm-router.service` ExecStart | `--host`, `--port`, `--api-key`, `--models-dir`, `--models-max`, `--models-preset`, `--sleep-idle-seconds`, `--timeout` |
| **模型级** | `router-preset.ini` 每模型 section | `n-gpu-layers`, `ctx-size`, `ubatch-size`, `threads`, `alias`, `spec-type`, `mlock`, `numa`, ... |

> 模型参数**仅在 INI 中定义**，不在 service 文件中重复。

### Preset INI（模型级参数）

**文件：** `~/model/router-preset.ini`

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

**修改模型参数：** 编辑 INI 文件 → `systemctl --user restart llm-router`

---

## 部署指南

### 架构

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

### 硬件

| 组件 | 规格 |
|------|------|
| 机型 | FEVM faex1 迷你主机 |
| APU | AMD Ryzen AI Max+ 395 (16C/32T) |
| 内存 | 128 GB LPDDR5X (256-bit, 统一内存) |
| 存储 | 1 TB NVMe SSD |
| 核显 | Radeon 8060S (RDNA 3.5, 40 CU, 2040 MHz) |
| GTT (GPU 可访问内存) | 120 GB (内核参数 `amdgpu.gttsize=122880`) |

**内存带宽：** 256-bit × 8000 MT/s ÷ 8 = **256 GB/s** 理论值，~200 GB/s 实际值。Dense 模型受内存带宽限制。

### 软件

| 组件 | 版本 / 详情 |
|------|------------|
| 推理机系统 | Ubuntu 26.04 LTS |
| 云端系统 | Ubuntu 24.04.4 LTS |
| llama.cpp | b9210 (commit c3f95c1f0, Vulkan 后端) |
| 编译选项 | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release`（+ BLAS/OpenMP/LTO/NATIVE） |
| Vulkan 运行时 | 1.4.341 |
| API 协议 | OpenAI 兼容 (`/v1/chat/completions`, `/v1/models`) |

**推理机路径布局：**

| 项目 | 路径 |
|------|------|
| 模型文件 + preset INI | `$HOME/model/` |
| llama-server 二进制 | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Router preset | `$HOME/model/router-preset.ini` |

### 模型清单

Router Mode 从 `$HOME/model/` 提供所有模型服务。一次只加载一个模型（`--models-max 1`），通过 LRU 按需切换。每个模型配置了 **alias 别名** 便于 API 路由。27B Q8 因可用性差（生成慢、长上下文 prefill 耗时过长）已从活跃名单中移除。

| 模型 | 文件名 | 别名 | 量化 | 架构 | 大小 | 激活参数 |
|------|--------|------|------|------|------|---------|
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | **358** | Q8_K_XL | **MoE** | ~37 GB | 3B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | **276** | Q6_K_XL | Dense | ~25 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | **274** | Q4_K_XL | Dense | ~17 GB | 27B |

> **别名命名规则：** 3 位数字 = 模型大小 + 量化等级。如 `358` = 35B Q8，`276` = 27B Q6，`274` = 27B Q4。API 请求的 `model` 字段使用别名或完整文件名均可。

### 1. 云端 Nginx 配置

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

        # 长超时（LLM 推理耗时，匹配 llama-server 超时）
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

### 2. 云端 SSL 配置

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

**验证：** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|gatewayports"`

### 4. SSH 反向隧道（systemd）

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

> 注：反向 SSH（-R 2222）已移除，仅保留 API 隧道。管理推理机请通过本地网络直连。

```bash
mkdir -p ~/.config/systemd/user
# 创建 service 文件后：
systemctl --user daemon-reload
systemctl --user enable llm-tunnel
systemctl --user start llm-tunnel
loginctl enable-linger   # 防止登出后服务终止
```

**手动测试隧道（先于 systemd）：**
```bash
# 在推理机上：
ssh -R 8080:127.0.0.1:12345 root@{your_server_ip} -N
# 在云端验证：
curl http://127.0.0.1:8080/v1/models
```

**SSH 密钥设置（免密登录）：**
```bash
ssh-keygen -t ed25519 -C "llm-tunnel@faex1"
ssh-copy-id root@{your_server_ip}
```

### 5. 推理服务（systemd）

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
| `/model 276` | 27B Q6 (Dense, 平衡) |
| `/model 274` | 27B Q4 (Dense, 最省资源) |

### 验证清单

- [ ] 云端 Nginx 配置已更新（含 `/v1/` 和 `/health` 端点）
- [ ] 云端 SSL 证书已配置
- [ ] 云端 `sshd_config` 允许 TCP 转发和 keepalive
- [ ] 推理机已配置免密登录云端
- [ ] `llm-tunnel.service` 已创建并 **运行中**
- [ ] 云端 `ss -tlnp | grep 8080` 确认隧道监听
- [ ] `llm-router.service` 已创建并 **运行中**（仅服务级参数）
- [ ] `~/model/router-preset.ini` 配置正确（模型级参数 + alias）
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回 3 个模型 + aliases
- [ ] 外网：`curl https://{your_domain}/health` 返回 `OK`
- [ ] 别名路由：`curl -d '{"model":"358",...}'` 路由到 35B-A3B Q8

**快速冒烟测试：**
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

*测试环境：FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9210 Vulkan · 2026-05-22*
