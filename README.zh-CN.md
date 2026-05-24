# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 暴露推理 API。

---

## 性能基准

所有基准测试均在 FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9299 Vulkan) 上完成。速度通过 API `timings` 测量（服务端，排除网络延迟）。Gen 速度含 thinking tokens。

### 35B-A3B MoE (Q8_K_XL, 别名 `358`)

**主力模型——生成速度最快，256K 稳定运行。** MoE 每 token 仅激活 35B 中的 3B 参数。

**最优配置：F16 KV cache。** ≤128K → UB=512（prefill +14~22%，TTFT -12~18% vs UB=256）。256K → UB=256（总耗时 -15% vs UB=512）。

**已排除：** UB=128（MTP 86%→65%，gen 更慢）；UB≥1024（p256K prefill -44%，TTFT +80%）；Q8_0 KV（反量化开销 > 稀疏 KV 带宽节省；所有 Q8_0 UB 均不如 F16 UB=256）；UB≥2048（Vulkan 崩溃 128K+）。

#### F16 KV UB=512（≤128K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 52.8 | 351.9 | 0.36s |
| p4K | 52.1 | 474.2 | 8.6s |
| p32K | 45.3 | 634.4 | 51.7s |
| p64K | 44.3 | 542.2 | 120.9s |
| p128K | 36.0 | 392.5 | 333.9s |
| p256K | 29.4 | 207.8 | 1163.6s |

#### F16 KV UB=256（256K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 54.4 | 340.2 | 0.37s |
| p4K | 56.6 | 391.3 | 10.5s |
| p32K | 46.9 | 520.1 | 63.0s |
| p64K | 45.5 | 448.1 | 146.2s |
| p128K | 36.5 | 344.6 | 380.4s |
| p256K | 28.4 | 238.2 | 1015.0s |

> Gen 速度在 UB=256/512 间几乎相同（±2 t/s）。UB 选择主要影响 prefill/TTFT：UB=512 在 ≤128K 更快；UB=256 在 256K 更快。

### 27B Dense Q8 (Q8_K_XL, 别名 `278`)

Dense 架构——每 token 激活全部 27B 参数。Q8_0 KV cache 解锁 256K 上下文并大幅提升长上下文 prefill。

**最优配置：Q8_0 KV + UB=512。**

**已排除：** F16 KV（p256K 超时 >7200s）；Q8_0 UB=256（p64K+ 比 UB=512 慢）；Q8_0 UB≥1024（p128K TTFT 退化 708→1137s）；UB≥2048（Vulkan 崩溃）。已知异常：Q8_0 KV UB≥512 时 p128 prefill 116→61 t/s（Vulkan Dense 大 KV + 高 UB 走慢路径）。

#### Q8_0 KV UB=512

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 12.0 | 61.1 | 2.1s |
| p4K | 13.0 | 125.2 | 32.7s |
| p32K | 11.1 | 204.9 | 160.0s |
| p64K | 10.4 | 264.3 | 248.0s |
| p128K | 9.3 | 185.1 | 708.3s |
| p256K | 6.8 | 138.6 | 1891.4s |

> p128K 总耗时：794s。p256K 总耗时：1983s（~33 分钟）。Q8_0 KV p128K prefill 比 F16 KV 快 271%（185 vs 50 t/s）。

### 27B Dense Q6 (Q6_K_XL, 别名 `276`)

Dense 架构 Q6 量化——速度与精度最佳平衡。

**最优配置：Q8_0 KV + UB=512。**

**已排除：** F16 KV UB≥512（p64K+ OOM/超时）；F16 KV UB=128（可跑 p256K 但总耗时 2× 慢于 Q8_0 KV：5671s vs 3111s）；Q8_0 UB=1024（p64K+ 略差）；UB≥2048（Vulkan 崩溃）。

#### Q8_0 KV UB=512

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 17.5 | 122.3 | 1.0s |
| p4K | 15.4 | 128.1 | 32.0s |
| p32K | 15.2 | 173.7 | 188.6s |
| p64K | 13.2 | 151.3 | 433.1s |
| p128K | 11.6 | 115.3 | 1136.9s |
| p256K | 8.0 | 80.2 | 3016.4s |

> p256K 总耗时：3111s（~52 分钟）。

### 27B Dense Q4 (Q4_K_XL, 别名 `274`)

Dense 架构 Q4 量化——Dense 模型中最快生成速度。

**最优配置：Q8_0 KV + UB=1024。**

**已排除：** F16 KV UB≥1024（p32K+ OOM）；F16 KV UB=128（可跑 p256K 但总耗时 1.8× 慢于 Q8_0 KV：5325s vs 2994s）；Q8_0 UB≤256（p32K+ 更慢）；UB≥2048（p256K Vulkan 崩溃）。

#### Q8_0 KV UB=1024

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 23.9 | 145.3 | 0.87s |
| p4K | 25.2 | 155.4 | 26.4s |
| p32K | 20.8 | 206.2 | 158.9s |
| p64K | 17.8 | 171.2 | 382.8s |
| p128K | 14.3 | 123.9 | 1058.0s |
| p256K | 10.0 | 82.9 | 2916.5s |

> p256K 总耗时：2994s（~50 分钟）。

### 跨模型对比（最优配置）

| Prompt | 35B MoE Q8 | 27B Q8 | 27B Q6 | 27B Q4 |
|--------|-----------|--------|--------|--------|
| p128 Gen | 52.8 | 12.0 | 17.5 | 23.9 |
| p4K Gen | 52.1 | 13.0 | 15.4 | 25.2 |
| p32K Gen | 45.3 | 11.1 | 15.2 | 20.8 |
| p64K Gen | 44.3 | 10.4 | 13.2 | 17.8 |
| p128K Gen | 36.0 | 9.3 | 11.6 | 14.3 |
| p256K Gen | 28.4† | 6.8 | 8.0 | 10.0 |
| p256K TTFT | 1015s† | 1891s | 3016s | 2917s |

> 配置：35B MoE = F16 KV（≤128K: UB=512, †256K: UB=256），27B Q8/Q6 = Q8_0 KV UB=512，27B Q4 = Q8_0 KV UB=1024。Gen 速度含 thinking tokens。

---

## 优化参数

### 关键决策及理由

| 决策 | 理由 |
|------|------|
| Service = 服务级，INI = 模型级 | 层次清晰，改模型参数不碰 service 文件 |
| 统一 256K 上下文 | -c 只预分配 KV cache，不影响性能；一套配置覆盖所有 prompt 长度 |
| 按量化等级差异化 ub | 量化越高权重越大，VRAM 余量越小，需更小 ub 保证稳定性；最优 UB 因模型而异（256–1024） |
| 不使用 `--cache-ram` | 统一内存上 pinned alloc 失败且慢 4.6%；默认 prompt cache 更优 |
| `--reasoning-budget 8192` | 防止思考 token 耗尽 KV cache/VRAM，无性能损失 |
| `-np 1` 强制 | MTP 不支持多 slot，5 并发速度降 75% |
| `--spec-draft-n-max 3` | 4 比 3 慢 20.6% |
| 全部模型 `-t 8` | 全 GPU 卸载下 t=8 vs t=16 无实质差异，t=8 更低温 |
| 不加 `--no-mmap` | 无收益，`--mmap`（默认）+ `--mlock` 是最佳组合 |
| `-a Qwen3.6` | 设置 API 响应中的 model 字段；客户端需校验 model 字段时必须 |
| alias 短名路由 | 无需符号链接；别名和文件名均可路由 |

### 使用约束

| 约束 | 值 | 原因 |
|------|---|------|
| 最大并发槽位 | 1 (`-np 1`) | **强制** — MTP 不支持多 slot |
| 35B MoE 最大上下文 | 256K | UB=512 ≤128K 最优；UB=256 256K 最优；UB≥1024 在 p256K 劣化；UB≥2048 Vulkan 崩溃 |
| 27B Dense 最大上下文 | 256K (Q8_0 KV) | 推荐 Q8_0 KV UB=512 (Q8/Q6) / UB=1024 (Q4)；F16 KV p256K 超时；UB≥2048 Vulkan 崩溃 |
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
reasoning-format = none
ctx-size = 262144
batch-size = 4096
ubatch-size = 512
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
reasoning-format = none
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
reasoning-format = none
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
reasoning-format = none
cache-type-k = q8_0
cache-type-v = q8_0
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
| llama.cpp | b9299 (commit b22ff4b7b, Vulkan 后端) |
| 编译选项 | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release`（+ BLAS/OpenMP/LTO/NATIVE） |
| Vulkan 运行时 | 1.4.341 |
| API 协议 | OpenAI 兼容 (`/v1/chat/completions`, `/v1/models`) |

**编译 llama.cpp：**

```bash
cd ~/llama/llama.cpp
git pull origin master                    # 更新源码
cmake -B build --fresh \
  -DGGML_VULKAN=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

> `--fresh` 重置 CMake 缓存（版本升级后推荐）。二进制文件：`build/bin/llama-server`。

**推理机路径布局：**

| 项目 | 路径 |
|------|------|
| 模型文件 + preset INI | `$HOME/model/` |
| llama-server 二进制 | `$HOME/llama/llama.cpp/build/bin/llama-server` |
| Router preset | `$HOME/model/router-preset.ini` |

### 模型清单

Router Mode 从 `$HOME/model/` 提供所有模型服务。一次只加载一个模型（`--models-max 1`），通过 LRU 按需切换。每个模型配置了 **alias 别名** 便于 API 路由。

| 模型 | 文件名 | 别名 | 量化 | 架构 | 大小 | 激活参数 |
|------|--------|------|------|------|------|----------|
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | **358** | Q8_K_XL | **MoE** | ~37 GB | 3B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | **278** | Q8_K_XL | Dense | ~33 GB | 27B |
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
        gzip off;              # 必须禁用 gzip 以支持 SSE 流式响应
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

# 安全：仅密钥认证（禁用密码登录）
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

> ⚠️ **重要：** Ubuntu 的 `/etc/ssh/sshd_config.d/` 目录包含 drop-in 文件（如 `50-cloud-init.conf`），会**覆盖**主配置。必须同时检查并编辑该目录下的文件，否则 `PasswordAuthentication no` 可能不生效。验证命令：`sudo sshd -T | grep passwordauthentication`

**应用：** `sudo systemctl restart ssh`

**验证：** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|passwordauthentication|pubkeyauthentication"`

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
ExecStart=/home/zxw/llama/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 --port 12345 \
    --api-key {your_api_key} \
    -a Qwen3.6 \
    --models-dir /home/zxw/model \
    --models-max 1 \
    --models-preset /home/zxw/model/router-preset.ini \
    --sleep-idle-seconds 600 \
    --timeout 3600
Restart=on-failure
RestartSec=10
WorkingDirectory=/home/zxw
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
| `/model 278` | 27B Q8 (Dense, 最高精度) |
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
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回 4 个模型 + aliases
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

*测试环境：FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9299 Vulkan · 2026-05-24*
