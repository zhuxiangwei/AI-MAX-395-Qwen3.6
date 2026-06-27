# AI-MAX-395-Qwen3.6

在 AMD Ryzen AI Max+ 395（Strix Halo）上使用 llama.cpp + Vulkan 部署 Qwen3.6 大语言模型，通过 SSH 反向隧道 + Nginx HTTPS 将推理 API 暴露到公网。

> 语音助手与监控播报子系统已独立为 [AI-MAX-395-Qwen3-ASR-TTS](https://github.com/yourname/AI-MAX-395-Qwen3-ASR-TTS) 项目。

---

## 性能基准

所有数据在 {your_machine}（AMD Ryzen AI Max+ 395，128 GB LPDDR5X，Radeon 8060S，llama.cpp r9784 Vulkan）上测量。

### 27B Dense Q8（别名 `278`）

Dense 模型，每个 token 激活全部 27B 参数。当前 Hermes 默认模型。配置：F16 KV + UB=256 + cache-ram=32768。

**生成速度（按上下文长度）：**

| 上下文 | P50 (t/s) | 平均 (t/s) |
|--------|-----------|------------|
| <4K    | 10.9      | 11.2       |
| 4–16K  | 11.8      | 11.8       |
| 16–64K | 12.7      | 12.3       |
| 64–130K| 10.0      | 10.2       |

**Prefill 速度（按 prompt 长度）：**

| Prompt 长度 | P50 (t/s) |
|-------------|-----------|
| <1K         | 38.1      |
| 1K–5K       | 40.2      |
| 5K–10K      | 54.0      |
| 10K–30K     | 132.6     |
| 30K–60K     | 93.2      |
| 60K–130K    | 63.9      |

> MTP 接受率：均值 87.1%，中位数 89.2%。短/中上下文生成稳定在 11–13 t/s。配置：q8_0 KV + UB=256 + cache-ram=49152。

### 35B-A3B MoE（别名 `358`）

MoE 模型，每个 token 仅激活 3B/35B 参数。~50 t/s 生成速度。配置：F16 KV + UB=256 + cache-ram=4096。

**生成速度（按上下文长度）：**

| 上下文  | P50 (t/s) | 平均 (t/s) |
|---------|-----------|------------|
| <4K     | 53.3      | 52.8       |
| 4–16K   | 48.3      | 49.0       |
| 16–64K  | 47.2      | 48.3       |
| 64–130K | 44.2      | 45.0       |

> MTP 接受率：均值 86.8%，中位数 88.2%（MoE 架构接受率偏低 ~40%）。配置：q8_0 KV + UB=256 + cache-ram=32768。

### 跨模型对比

| Prompt | 35B UD-Q8 | 27B Q8 |
|--------|-----------|--------|
| p128 Gen | 56.7 t/s  | 13.8 t/s |
| p4K Gen  | 56.7 t/s  | 13.4 t/s |
| p32K Gen | 50.1 t/s  | 12.5 t/s |
| p64K Gen | 46.7 t/s  | 12.1 t/s |
| p128K Gen| 38.0 t/s  | 10.0 t/s |

---

## 部署指南

### 架构

```
┌──────────────┐  HTTPS (443)  ┌────────────────┐
│   Client     │ ────────────▶ │  Cloud Nginx    │
│  (任意设备)   │               │  {your_domain}  │
└──────────────┘               └────────┬────────┘
                                       │
                           proxy_pass 127.0.0.1:8080
                                       │
┌──────────────┐   SSH 反向隧道         │
│ Inference Box│ ◀──────────────────────┘
│ Ubuntu 26.04 │ 127.0.0.1:8080 ←→ 12345
│ AMD AI Max+395│
│ 128 GB RAM   │
└──────────────┘
```

llama.cpp 仅绑定 `127.0.0.1:12345`，云服务器运行 Nginx（端口 443），SSH 反向隧道提供 NAT 穿透。

### 硬件

| 组件 | 规格 |
|------|------|
| APU | AMD Ryzen AI Max+ 395（16C，SMT 已禁用） |
| 内存 | 128 GB LPDDR5X（统一内存） |
| iGPU | Radeon 8060S（RDNA 3.5，40 CU） |
| GTT | 120 GB（`amdgpu.gttsize=122880`） |

### BIOS 配置

| 设置 | 值 |
|------|-----|
| SMT | **禁用** |
| iGPU Mem Bar | **ResizableBAR** |
| UMA Version | **Non-Legacy** |
| Dedicated Graphics Memory | **0.5G** |

### GRUB 内核参数

```bash
GRUB_CMDLINE_LINUX_DEFAULT="amd_iommu=off amdgpu.gttsize=122880 processor.max_cstate=1"
```

**应用：** `sudo update-grub && sudo reboot`

### 软件

| 组件 | 版本 |
|------|------|
| 推理机 OS | Ubuntu 26.04 LTS |
| 云服务器 OS | Ubuntu 24.04.4 LTS |
| llama.cpp | r9784（Vulkan 后端） |
| 编译选项 | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` |

**编译 llama.cpp：**

```bash
cd ~/llama.cpp
git pull origin master
cmake -B build --fresh -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

### 模型清单

| 别名 | 文件 | 架构 | 大小 | 激活参数 | 角色 |
|------|------|------|------|----------|------|
| **278** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | Dense | ~33 GB | 27B | 主模型（Hermes 默认，支持视觉，语音助手常驻） |
| **358** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | MoE | ~37 GB | 3B | 备用模型（快速响应，按需加载） |

单模型模式（`--models-max 1`），278 常驻不 sleep，358 按需加载。Router 通过 LRU 自动切换。

### 1. 云端 Nginx 配置

**文件：** `/etc/nginx/sites-enabled/default`

```nginx
server_tokens off;
gzip off;
limit_req_zone $binary_remote_addr zone=api:10m rate=60r/m;

server {
    listen 443 ssl default_server;
    client_max_body_size 64m;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location = /v1/props {
        access_log off;
        default_type application/json;
        return 200 '{}';
    }

    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        limit_req zone=api burst=20 nodelay;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        gzip off;
    }

    location /health {
        limit_req zone=api burst=20 nodelay;
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**应用：** `sudo nginx -t && sudo systemctl reload nginx`

### 2. SSH 反向隧道

**文件：** `~/.config/systemd/user/llama-tunnel.service`

```ini
[Unit]
Description=LLM SSH Reverse Tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 8080:127.0.0.1:12345 \
    -N \
    {your_server_user}@{your_server_ip}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now llama-tunnel
loginctl enable-linger
```

### 3. 硬件温度监控

**脚本：** `~/scripts/hw-temp.sh`

```bash
#!/bin/bash
# 硬件温度/负载综合日志
# 记录 GPU(amdgpu) / CPU(k10temp) / NVMe / 网卡 等温度 + GPU 负载
INTERVAL=60
LOGFILE="/home/zxw/logs/hw-temp.log"
mkdir -p "$(dirname "$LOGFILE")"
while true; do
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    busy=$(cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1)
    gpu=$(cat /sys/class/hwmon/hwmon7/temp1_input 2>/dev/null)
    cpu=$(cat /sys/class/hwmon/hwmon4/temp1_input 2>/dev/null)
    nvme=$(cat /sys/class/hwmon/hwmon2/temp1_input 2>/dev/null)
    nic_r8169=$(cat /sys/class/hwmon/hwmon3/temp1_input 2>/dev/null)
    nic_eno1=$(cat /sys/class/hwmon/hwmon5/temp1_input 2>/dev/null)
    wifi=$(cat /sys/class/hwmon/hwmon6/temp1_input 2>/dev/null)
    gpu=${gpu:+$((gpu / 1000))}
    cpu=${cpu:+$((cpu / 1000))}
    nvme=${nvme:+$((nvme / 1000))}
    nic_r8169=${nic_r8169:+$((nic_r8169 / 1000))}
    nic_eno1=${nic_eno1:+$((nic_eno1 / 1000))}
    wifi=${wifi:+$((wifi / 1000))}
    echo "$ts gpu_busy=${busy:-0}% gpu=${gpu:-NA}°C cpu=${cpu:-NA}°C nvme=${nvme:-NA}°C r8169=${nic_r8169:-NA}°C eno1=${nic_eno1:-NA}°C wifi=${wifi:-NA}°C" >> "$LOGFILE"
    sleep "$INTERVAL"
done
```

**服务：** `~/.config/systemd/user/hw-temp.service`

```ini
[Unit]
Description=Hardware Temperature Logger

[Service]
Type=simple
ExecStart=/bin/bash -c '/home/$USER/scripts/hw-temp.sh'
Restart=on-failure
RestartSec=10
```

### 4. llama.cpp 配置文件

**Preset INI：** `~/model/router-preset.ini`

```ini
; Router preset - 所有模型由 Router 统一管理
; models-max=1: 同一时刻只加载一个模型，避免内存竞争
;
; cache-idle-slots: 全部开启（默认），空闲KV cache存入cache-ram释放显存
; timeout: HTTP 并发等待窗口

[Qwen3.6-27B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = auto
kv-unified = 1
parallel = 2
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
spec-type = draft-mtp
spec-draft-n-max = 3
cache-ram = 49152
cache-type-k = q8_0
cache-type-v = q8_0
mmproj = /home/zxw/mmproj/mmproj-Qwen3.6-27B-F16.gguf
image-min-tokens = 2048
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
sleep-idle-seconds = 1800
alias = 278
timeout = 3600

[Qwen3.6-35B-A3B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = auto
kv-unified = 1
parallel = 4
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
spec-type = draft-mtp
spec-draft-n-max = 2
cache-ram = 32768
cache-type-k = q8_0
cache-type-v = q8_0
mmproj = /home/zxw/mmproj/mmproj-Qwen3.6-35B-A3B-F16.gguf
image-min-tokens = 2048
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
sleep-idle-seconds = 600
alias = 358
timeout = 3600
```

**Router 服务：** `~/.config/systemd/user/llama-router.service`

```ini
[Unit]
Description=llama.cpp Router Server
After=network.target

[Service]
Type=simple
ExecStart=/home/$USER/scripts/llama-router.sh
Restart=on-failure
RestartSec=10
TimeoutStartSec=300
TimeoutStopSec=35
KillMode=process
LimitMEMLOCK=infinity

[Install]
WantedBy=default.target
```

**Router 启动脚本：** `~/scripts/llama-router.sh`

```bash
#!/bin/bash
# Qwen3.6 LLM Router Service (systemd compatible - foreground)

LOGDIR="/home/zxw/logs/llama"
BINDIR="/home/zxw/llama.cpp/build/bin"
ROUTER="$BINDIR/llama-server"

export LD_LIBRARY_PATH="$BINDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Vulkan: 限制每批提交节点数，避免 APU GPU job timeout (ErrorDeviceLost)
export GGML_VK_MAX_NODES_PER_SUBMIT=1

mkdir -p "$LOGDIR"

exec "$ROUTER" \
  --host 127.0.0.1 \
  --port 12345 \
  --api-key YOUR_API_KEY \
  -a Qwen3.6 \
  --models-dir /home/zxw/model \
  --models-max 1 \
  --models-preset /home/zxw/model/router-preset.ini \
  --metrics \
  >> "$LOGDIR/router.log" 2>&1
```

**TTS 服务：** `~/.config/systemd/user/qwen3-tts.service`

```ini
[Unit]
Description=Qwen3-TTS Service
After=network.target

[Service]
Type=simple
ExecStart=/home/zxw/scripts/qwen3-tts.sh
Restart=on-failure
RestartSec=10
TimeoutStartSec=120

[Install]
WantedBy=default.target
```

**TTS 启动脚本：** `~/scripts/qwen3-tts.sh`

```bash
#!/bin/bash
# Qwen3-TTS Server (systemd compatible - foreground)
# Model: Qwen3-TTS-12Hz-0.6B-CustomVoice (9 preset speakers)

LOGDIR="/home/zxw/logs/tts"
BINDIR="/home/zxw/qwen3-tts/build/bin"
TTS="$BINDIR/qwen_tts"
MODEL_DIR="/home/zxw/model-tts/Qwen3-TTS-12Hz-0.6B-CustomVoice"
PORT=12348
THREADS=8

mkdir -p "$LOGDIR"

exec "$TTS" --serve "$PORT" -d "$MODEL_DIR" -j "$THREADS" -S >> "$LOGDIR/tts.log" 2>&1
```

**ASR 服务：** `~/.config/systemd/user/qwen3-asr.service`

```ini
[Unit]
Description=Qwen3-ASR-1.7B STT Service
After=network.target

[Service]
Type=simple
ExecStart=/home/zxw/scripts/qwen3-asr.sh
LimitMEMLOCK=infinity
Restart=on-failure
RestartSec=10
TimeoutStartSec=120
TimeoutStopSec=15
KillMode=process

[Install]
WantedBy=default.target
```

**ASR 启动脚本：** `~/scripts/qwen3-asr.sh`

```bash
#!/bin/bash
LOGDIR="/home/zxw/logs/llama"
BINDIR="/home/zxw/llama.cpp/build/bin"
SERVER="$BINDIR/llama-server"
MODEL="/home/zxw/model-asr/Qwen3-ASR-1.7B-Q8_0.gguf"
MMPROJ="/home/zxw/mmproj/mmproj-Qwen3-ASR-1.7B-Q8_0.gguf"

export LD_LIBRARY_PATH="$BINDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$LOGDIR"

exec "$SERVER" \
  --host 127.0.0.1 \
  --port 12347 \
  --model "$MODEL" \
  --mmproj "$MMPROJ" \
  --ctx-size 65536 \
  --n-gpu-layers 0 \
  --threads 8 \
  --parallel 1 \
  --no-cache-idle-slots \
  --cache-ram 0 \
  --timeout 600 \
  >> "$LOGDIR/asr.log" 2>&1
```

### 5. 模型切换

客户端在 API 请求中指定 `model` 字段，别名和完整文件名均可：

```bash
# 使用别名
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer ***" \
  -d '{"model": "278", ...}'

curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer ***" \
  -d '{"model": "358", ...}'
```

### 客户端集成

**Hermes Agent：** 默认模型 `278`，provider `local-llm` → `https://{your_domain}/v1`，超时 7200s。

**opencode：** 配置 `~/.config/opencode/opencode.jsonc`，主模型和辅助模型均使用 278。

**QClaw：** 通过云端代理 `http://127.0.0.1:19000/proxy/llm`，支持微信/QQ 多渠道。

### 语音助手与监控播报

语音助手和监控播报子系统已独立为 [AI-MAX-395-Qwen3-ASR-TTS](https://github.com/yourname/AI-MAX-395-Qwen3-ASR-TTS) 项目，包含麦克风录音、ASR 识别、LLM 对话、TTS 语音输出和硬件监控播报功能。

### 验证清单

- [ ] 云端 Nginx 配置已更新（`/v1/` + `/health`）
- [ ] 云端 SSH 允许 TCP 转发和保活
- [ ] `llama-tunnel.service` 活跃
- [ ] `llama-router.service` 活跃（`--models-max 1`）
- [ ] `router-preset.ini` 已配置（278 + 358）
- [ ] 外部 `curl https://{your_domain}/health` 返回 `OK`
- [ ] `hw-temp.service` 活跃
- [ ] `qwen3-tts.service` 活跃
- [ ] `qwen3-asr.service` 活跃
- [ ] `ai-station.service` 活跃
- [ ] 别名路由 `curl -d '{"model":"278",...}'` 和 `{"model":"358",...}` 均可工作

**快速测试：**

```bash
curl https://{your_domain}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"model":"278","messages":[{"role":"user","content":"Hello"}],"max_tokens":50,"stream":true}'
```

---

*{your_machine} · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp r9784 Vulkan*
