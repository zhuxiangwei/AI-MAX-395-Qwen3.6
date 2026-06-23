# 语音助手与硬件监控播报系统需求文档

> **实现状态（2026-06-23 v2）**
> - ✅ 监控播报链路：已上线运行（`monitor-broadcast.service` v7）
> - ✅ TTS 语音合成：Qwen3-TTS-12Hz-1.7B-CustomVoice 已部署（port 12348，音色 vivian）
> - ✅ 音频播放：ALSA card1 扬声器，非流式 WAV 播放
> - ✅ TTS 播放策略：非流式为主（默认），流式预缓冲保留（`TTS_USE_STREAM` 开关）
> - ✅ 音量控制：TTS 不管理音量，系统 ALSA 音量固定 95%
> - ✅ 麦克风录音：已完成（card 1 ALC245 `default_capture`，VAD 能量检测，支持校准）
> - ✅ ASR：已调通（port 12347，OpenAI 兼容 API，`<asr_text>` 格式解析正常）
> - ✅ LLM 对话：已完成（OpenAI SDK + tool calling，6 个工具，端口 12346 专用实例无需 API Key）
> - ✅ 语音助手链路：Mic → VAD → ASR → LLM（tool calling）→ TTS → 播放，全链路代码完成
> - 🔧 待调试：ASR 识别准确率、Bing 搜索是否被拦、GPU 信息获取方式（Vulkan 后端）

## 1. 项目概述

构建一个运行在推理机上的**纯 CPU 语音交互与监控播报系统**。系统包含两条独立但共享 TTS 资源的核心链路：

1. **语音助手链路**：麦克风录音 → VAD → ASR 识别 → LLM 队列调度（tool calling）→ TTS 语音输出。
2. **监控播报链路 (Kernel Log Speaker)**：独立线程实时监控核心硬件（358/278 GPU、CPU、内存），异常时实时 TTS 播报。

**核心约束**：ASR 和 TTS 均运行在纯 CPU 环境下，LLM (Qwen3.6 35B-A3B) 运行在 GPU 上（专用实例 port 12346，与 router 12345 隔离）。

---

## 2. 系统架构

```
麦克风 (card 1/2)
  → VAD (能量阈值检测)
    → WAV 文件 (44100/2ch/S16_LE)
      → ASR (Qwen3-ASR-1.7B, port 12347)
        → 识别文本
          → LLM (Qwen3.6-35B-A3B 专用实例, port 12346, 无需 API Key)
            → tool calling（get_time / get_system_info / web_search / get_weather / browse_url / calculator）
              → 回复文本
                → TTS (Qwen3-TTS-12Hz-1.7B-CustomVoice, port 12348)
                  → WAV → aplay → 扬声器 (card 1)

监控播报（独立线程）
  → router.log 解析 + gpu-temp.log 解析 + /proc 采集
    → 阈值/关键字判断
      → TTS 队列（优先级抢占，最大 3 条）
        → TTS → aplay → 扬声器 (card 1)
```

---

## 3. 功能需求

### 3.1 语音助手链路 (Voice Assistant Pipeline)

#### 3.1.1 麦克风录音（✅ 已完成）

**实现文件**：`mic_recorder.py`

*   **录音设备**：
    *   `default_capture` (card 1 ALC245 Analog, 3.5mm 麦克风) — 当前使用
    *   card 2 `acp-pdm-mach` DMIC 阵列 — 备选（未测试）
*   **录音参数**：
    *   采样率：44100 Hz（ALSA 设备原生采样率，不做降采样）
    *   格式：S16_LE（16-bit PCM）
    *   声道：2ch 立体声（取左声道做 VAD 检测）
*   **语音活动检测 (VAD)**：
    *   方案：左声道 RMS 能量阈值检测
    *   帧大小：30ms（1323 samples/frame）
    *   静音超时：1.5s 自动停止录音
    *   预语音缓冲：0.3s（防止截断说话开头）
    *   最大录音时长：30s
    *   最小语音时长：0.3s（低于此丢弃）
    *   监听超时：60s 无语音自动返回
    *   启动预热：跳过前 10 帧（arecord 填充噪声）
*   **校准模式**：`--calibrate` 录制 2s 环境噪声，建议阈值 = max(avg * 3, 200)
*   **录音流程**：
    1. 启动 arecord 常驻进程（raw PCM 输出）
    2. 持续按帧读取，计算左声道 RMS
    3. RMS > 阈值 → 开始录音（含预缓冲）
    4. RMS < 阈值持续 1.5s → 停止录音
    5. 保存为 WAV → 送入 ASR

#### 3.1.2 ASR 语音识别（✅ 已调通）

**实现文件**：`asr_module.py`

*   **模型**：Qwen3-ASR-1.7B-Q8_0.gguf（纯 CPU 推理，port 12347）
*   **服务**：llama-server + mmproj，systemd 用户服务 `llama-asr.service`
*   **启动参数**：`--ctx-size 65536 --n-gpu-layers 0 --threads 8 --timeout 600`
*   **接口**：OpenAI 兼容 `/v1/audio/transcriptions`
    *   `POST` with `multipart/form-data`
    *   `files={'file': (name, f, 'audio/wav')}` + `data={'model': 'Qwen3-ASR-1.7B'}`
*   **输出格式解析**：
    *   原始输出：`language Chinese<asr_text>实际内容`
    *   用 `<asr_text>` 标签提取，兜底去掉 `language` 前缀
*   **超时**：60s

#### 3.1.3 LLM 对话与工具调用（✅ 已完成）

**实现文件**：`llm_module.py` + `tools.py`

*   **模型**：Qwen3.6-35B-A3B-UD-Q8_K_XL（GPU，port 12346，专用 llama-server 实例，无需 API Key）
*   **客户端**：`openai` Python SDK（OpenAI 兼容协议）
*   **对话参数**：temperature=0.6, top_p=0.95, max_tokens=1024
*   **System Prompt**：简洁口语化，不超过两三句话，不用 markdown/表格/代码块
*   **对话历史**：最多保留最近 10 轮（5 轮对话对）
*   **Tool Calling 机制**：
    1. 每次请求携带 `tools` 定义
    2. LLM 返回 `finish_reason == "tool_calls"` → 执行工具 → 结果回喂
    3. 最多 5 轮 tool calling，防止死循环
    4. LLM 返回最终文本 → 结束

**可用工具（6 个）**：

| 工具 | 用途 | 数据源 | 依赖 |
|------|------|--------|------|
| `get_time` | 当前日期时间 | 本地 datetime | 无 |
| `get_system_info` | 内存/CPU/GPU温度/磁盘/服务状态 | /proc, rocm-smi, systemctl | 无 |
| `web_search` | 通用互联网搜索 | Bing 直接爬取 | `requests` |
| `get_weather` | 城市天气查询 | 内部调 web_search | `requests` |
| `browse_url` | 抓取网页文本内容 | Playwright headless Chromium | `playwright` + chromium |
| `calculator` | 数学计算 | math 模块 | 无 |

**网络环境适配**：
*   `web_search`：使用 Bing（国内可访问），回退 Sogou（预留）
*   `get_weather`：通过搜索"城市 天气"获取，不依赖外部天气 API
*   `browse_url`：Playwright headless 浏览器，处理 JS 渲染/反爬
*   所有工具均为国内可用方案（无 DuckDuckGo、wttr.in、Jina Reader 等被墙服务）

*   **LLM 调度**：
    *   35B-A3B 专用实例（port 12346）与 router（port 12345）隔离，互不影响
    *   专用实例已常驻，无需冷加载
    *   timeout=300s

#### 3.1.4 TTS 语音合成（✅ 已完成）

**实现文件**：`tts_module.py`

*   **推理底座**：Qwen3-TTS-12Hz-1.7B-CustomVoice（llama.cpp GGUF 纯 CPU 推理）
    *   systemd 用户服务 `qwen-tts.service`（port 12348）
    *   启动参数：`-S`（流式模式）+ `-j 8`（8 线程）
    *   音色：vivian（中文女声），language=chinese
*   **播放策略**：非流式 WAV 播放
    *   通过 `/v1/tts` 端点请求完整音频
    *   生成完整 WAV 文件后用 `aplay` 播放
    *   流式预缓冲模式已废弃（纯 CPU 性能不够，RTF ~1.8-2.5）
*   **TTS 请求参数**：
    *   `speaker`: "vivian"（字符串名，非数字 ID）
    *   `language`: "chinese"
    *   `seed`: 42（固定种子，确保同一文本音色一致）
    *   `ensure_ascii=False`（中文字符 UTF-8 直接发送）
*   **播放方式**：`systemd-run --user --no-block aplay -q -D default <wav>`（非阻塞）
*   **音量控制**：
    *   TTS 服务**不管理音量**（不传 volume 参数）
    *   系统 ALSA 音量固定 95%

### 3.2 监控播报线程 (Kernel Log Speaker)

#### 3.2.1 监控对象（✅ 已实现）

**实现文件**：`monitor-broadcast.py`

*   **GPU (358/278 - AMD)**：
    *   温度 (Temperature)
    *   显存占用 (Memory Usage)
    *   利用率 (Utilization)
    *   功耗 (Power)
    *   **数据源**：`gpu-temp.log`（cron 5min 写入）+ `router.log` 日志文件
    *   **gpu-temp.log 数据源**：`gpu-temp-log.sh` 从 amdgpu hwmon 读取（temp1=edge, temp2=junction, temp3=memory）+ `gpu_busy_percent` + `power1_input` + `/proc/meminfo`
    *   **提取指标**：从日志中实时提取显存峰值、温度告警、OOM、`Fatal`、`Error`（E 级别）、`Xid` 等
*   **CPU**：
    *   负载 (Load Average) — `/proc/loadavg`
*   **内存**：
    *   可用内存 / 交换分区使用率（`/proc/meminfo`）

#### 3.2.2 播报逻辑（✅ 已实现）

*   **独立线程**：与语音助手链路隔离，互不阻塞。已部署为 `monitor-broadcast.service`
*   **双频率轮询**：
    *   快速轮询（180s）：模型切换 + 推理任务全生命周期（启动/prefill完成/生成里程碑/结束/空闲）
    *   慢速轮询（300s）：硬件告警 + 日志 E/F 级别 + 日常播报（30min 间隔）
*   **触发条件**：
    *   *阈值报警*：GPU 温度 > 80°C（警告）/ 90°C（严重），内存 > 80%（警告）/ 90%（严重），GPU 功耗 > 120W（警告）/ 130W（严重）
    *   *关键字报警*：日志中出现 OOM、Xid、段错误、Vulkan 崩溃（`vk::DeviceLostError`）、Fatal、Error（E 级别）、子进程崩溃等
*   **播报策略**：
    *   **去重**：同类严重告警 5 分钟内不重复播报
    *   **优先级抢占**：severity ≥ 3 的严重告警直接插入 TTS 队列头部
    *   **TTS 队列**：独立线程发送，队列上限 3 条，超出丢弃
    *   **全局冷却**：非严重告警 5 分钟冷却期
*   **TTS 播放策略**：
    *   默认非流式（`TTS_USE_STREAM = False`）：完整生成 WAV 后播放，优先稳定性
    *   流式预缓冲模式保留（`_speak_prebuffer`），通过 `TTS_USE_STREAM` 开关切换
    *   所有 TTS 请求强制 `language=chinese` + `ensure_ascii=False` + `seed=42`
    *   日常播报包含 CPU 负载、GPU 负载、温度、内存信息
    *   任务编号逐位中文朗读（如 26640 → 二六六四零）
*   **日志轮转**：`RotatingFileHandler`，单文件 5MB，保留 3 个备份

#### 3.2.3 播报文案分类

| 类别 | 示例文案 | 优先级 |
|------|----------|--------|
| OOM | "严重警告！显存溢出！" | 3（严重） |
| Xid 错误 | "显卡报错！Xid 错误！" | 3 |
| 段错误 | "段错误！进程可能崩溃！" | 3 |
| Fatal | "致命错误！" | 3 |
| Vulkan 崩溃 | "Vulkan 崩溃！" | 3 |
| 子进程崩溃 | "推理进程异常退出！" | 3 |
| GPU 温度严重 | "温度严重告警！{temp} 度！" | 3 |
| GPU 功耗严重 | "功耗严重告警！{watt} 瓦！" | 3 |
| 内存严重 | "内存严重不足！{pct}%！" | 3 |
| Error（E 级） | "检测到错误日志。" | 2 |
| GPU 温度警告 | "温度 {temp} 度，偏高。" | 1 |
| GPU 功耗警告 | "功耗 {watt} 瓦。" | 1 |
| 内存警告 | "内存使用偏高，{pct}%。" | 1 |
| 模型切换 | "模型已切换到 {model}。" | 1 |
| 任务开始 | "新任务 {task_id}，开始推理。" | 1 |
| 任务完成 | "任务 {task_id} 完成，共 {tokens} 个 token。" | 1 |
| 日常播报 | "一切正常。CPU 负载 X，GPU X%，温度 X 度，内存 X%。" | 0 |
| 空闲 | "系统运行平稳。" | 0 |

---

## 4. 非功能需求

### 4.1 性能指标

*   **ASR 延迟**：< 500ms（GGUF CPU 推理，1.7B 模型）
*   **LLM 响应**：取决于模型大小，router 自带 `models-max=1` 排队
*   **TTS RTF**：~1.8-2.5（纯 CPU 8 线程，llama.cpp GGUF 推理）
*   **录音→识别→回复→播放 全链路延迟**：< 10s（目标）

### 4.2 资源管理

*   **128GB 统一内存**：
    *   推理机配备 128GB 统一内存，大模型部署占用大部分，空余内存充足
    *   ASR 模型 ~1.6GB / TTS 模型 ~12GB / LLM ~37GB
    *   内存不再是瓶颈
*   **并发**：支持至少 1 个用户对话 + 1 个监控播报并发

### 4.3 可靠性

*   **异常恢复**：TTS/ASR 进程崩溃后 systemd 自动重启（Restart=on-failure）
*   **日志记录**：所有 ASR 文本、LLM 回复、TTS 生成耗时、监控报警均记录到本地日志文件
*   **信号处理**：SIGTERM/SIGINT 优雅退出，保存 state.json

---

## 5. 技术栈

| 组件 | 技术选型 | 备注 |
| :--- | :--- | :--- |
| **语言** | Python 3.10+ | 生态丰富 |
| **ASR** | llama.cpp / Qwen3-ASR-1.7B GGUF | 纯 CPU，port 12347 |
| **TTS** | llama.cpp GGUF (Qwen3-TTS-12Hz-1.7B-CustomVoice) | 纯 CPU，port 12348，非流式 WAV |
| **LLM** | llama.cpp (Qwen3.6-35B-A3B 专用实例) | GPU，port 12346，无需 API Key |
| **LLM 客户端** | `openai` Python SDK | OpenAI 兼容协议 + tool calling |
| **工具调用** | 自定义 tools.py | 6 个工具，全部国内可用 |
| **录音** | `arecord` + 自定义 VAD | ALSA 直接采集，44100/S16_LE/2ch |
| **VAD** | 左声道 RMS 能量阈值检测 | 支持校准模式 |
| **音频播放** | `aplay` | ALSA default，WAV 文件播放 |
| **网页抓取** | Playwright headless Chromium | 处理 JS 渲染/反爬 |
| **搜索** | Bing 直接爬取 | 无需 API key，国内可用 |
| **监控采集** | `/proc`, amdgpu hwmon, `regex` | 读取 CPU/内存/GPU 指标 + 日志解析 |
| **任务队列** | `threading` + `deque` | 本地内存队列，TTS 队列最大 3 条 |
| **音量控制** | ALSA 系统级 | 固定 95%，无应用层音量管理 |

---

## 6. 接口设计

### 6.1 ASR 接口

```http
POST /v1/audio/transcriptions
Content-Type: multipart/form-data

file: <wav_file>       // 44100Hz S16_LE 2ch WAV
model: Qwen3-ASR-1.7B

// Response: {"text": "language Chinese<asr_text>实际内容"}
// 端口 12347，无需 API Key
```

### 6.2 TTS 接口

```http
POST /v1/tts
Content-Type: application/json

{
  "text": "播报内容",
  "speaker": "vivian",
  "language": "chinese",
  "seed": 42
}

// Response: WAV audio data (S16_LE/24000Hz/1ch)
// 端口 12348，无需 API Key
```

### 6.3 LLM 接口

```http
POST /v1/chat/completions
Content-Type: application/json

{
  "model": "Qwen3.6-35B-A3B-UD-Q8_K_XL",
  "messages": [...],
  "tools": [...],
  "temperature": 0.6,
  "top_p": 0.95,
  "max_tokens": 1024
}

// 端口 12346，无需 API Key（专用实例，非 router）
```

### 6.4 监控播报配置

```json
{
  "gpu_ids": [358, 278],
  "thresholds": {
    "gpu_temp_warn": 80,
    "gpu_temp_crit": 90,
    "gpu_pwr_warn": 120,
    "gpu_pwr_crit": 130,
    "mem_warn_pct": 80,
    "mem_crit_pct": 90
  },
  "keywords": ["OOM", "Xid", "Fatal", "Error", "segfault", "DeviceLost", "child crash"],
  "fast_poll_seconds": 180,
  "slow_poll_seconds": 300,
  "cooldown_seconds": 300,
  "alert_dedup_seconds": 300,
  "daily_interval_seconds": 1800,
  "tts_queue_max": 3
}
```

---

## 7. 部署与环境

*   **运行环境**：推理机 (Linux, Ubuntu 26.04)
*   **硬件**：
    *   CPU/APU：AMD RYZEN AI MAX+ 395（8 核 16 线程，集成 Radeon 8060S）
    *   RAM：128GB 统一内存
    *   扬声器：ALC245 Analog (card 1, device 0)
    *   麦克风：acp-pdm-mach DMIC 阵列 (card 2, device 0) / ALC245 3.5mm (card 1)
*   **systemd 用户服务**：
    *   `llama-router.service` — LLM router (port 12345，供 Hermes/QClaw)
    *   `qwen3.6-35b-a3b.service` — 35B-A3B 语音助手专用 (port 12346)
    *   `qwen-tts.service` — TTS 合成 (port 12348)
    *   `llama-asr.service` — ASR 识别 (port 12347)
    *   `monitor-broadcast.service` — 监控播报 v7
    *   `gpu-temp-log.service` + `gpu-temp-log.timer` — GPU 温度日志（每 5 分钟）
    *   `logrotate.service` + `logrotate.timer` — 日志轮转
    *   `llm-tunnel.service` — LLM SSH 隧道
*   **启动脚本**（`/home/zxw/scripts/`）：
    *   `llama-router.sh` — router 启动，含 SIGTERM checkpoint 保存
    *   `qwen-tts.sh` — TTS 服务启动（`-S` 流式 + `-j 8` 线程）
    *   `llama-asr.sh` — ASR 服务启动（纯 CPU，`--ctx-size 65536`）
    *   `gpu-temp-log.sh` — GPU 温度/功耗/内存日志（从 amdgpu hwmon 读取）
    *   `slot-checkpoint.sh` — KV cache 保存/恢复（save/restore/clear）
*   **模型配置**（`/home/zxw/model/router-preset.ini`）：
    *   `Qwen3.6-27B-UD-Q8_K_XL`（alias: 278）— ctx 262K，cache 48GB，slot checkpoint
    *   `Qwen3.6-35B-A3B-UD-Q8_K_XL`（alias: 358）— ctx 262K，cache 64GB，mmproj 多模态，slot checkpoint
    *   通用参数：flash-attn, kv-unified, parallel=1, mlock, numa=distribute, reasoning-budget=16384
*   **音频配置**：
    *   ALSA `default_capture` = dsnoop → hw:1,0 (ALC245 录音共享)
    *   ALSA `pcm.!default` = dmix → hw:1,0 (ALC245 播放共享)
    *   ALSA 音量固定 95%
*   **日志目录**：
    *   `/home/zxw/logs/llama/router.log` — LLM router 日志
    *   `/home/zxw/logs/llama/asr.log` — ASR 日志
    *   `/home/zxw/logs/tts/tts.log` — TTS 日志
    *   `/home/zxw/logs/gpu-temp.log` — GPU 温度日志
    *   `/home/zxw/logs/monitor/monitor.log` — 监控播报日志（5MB x 3 轮转）
*   **状态文件**：`/home/zxw/.config/monitor-broadcast/state.json`（原子写入）

---

## 8. 开发计划

### Phase 1：麦克风录音（✅ 已完成）
- [x] 实现基于 ALSA 的录音模块（arecord + 自定义 VAD）
- [x] 实现语音活动检测（RMS 能量阈值）
- [x] 录音保存为 44100/2ch/S16_LE WAV
- [x] 校准模式（`--calibrate`）
- [ ] 测试两个录音设备（DMIC / 3.5mm）选择最佳

### Phase 2：ASR 对接（✅ 已完成）
- [x] 调通 ASR 请求格式（multipart/form-data，`<asr_text>` 解析）
- [x] 录音 → ASR → 文本 全链路测试（`--test-asr`）

### Phase 3：LLM 调度（✅ 已完成）
- [x] OpenAI SDK 客户端 + tool calling 循环
- [x] 6 个工具实现（get_time / get_system_info / web_search / get_weather / browse_url / calculator）
- [x] 网络环境适配（Bing 搜索、Playwright 网页抓取）
- [x] ASR 文本 → LLM → 回复文本 全链路测试（`--test-llm`）
- [ ] GPU 信息获取方式确认（Vulkan 后端，rocm-smi TODO）

### Phase 4：TTS 对接（✅ 已完成）
- [x] 回复文本 → TTS → WAV → aplay 全链路测试
- [x] 监控播报与语音助手 TTS 资源共享（独立 TTS 队列 + 非阻塞播放）
- [ ] 全链路联调（Mic → ASR → LLM → TTS → 播放）

### Phase 5：集成与优化（待开始）
- [ ] 全链路联调
- [ ] 性能优化
- [ ] 异常处理与重试
- [ ] 麦克风设备选择（DMIC vs 3.5mm）
- [ ] LLM 应用层 FIFO 缓存队列（低优先级）

---

## 9. 后续优化方向

1.  **VAD 优化**：从能量阈值升级到 WebRTC VAD 或神经网络 VAD
2.  **TTS 性能**：如需更低延迟可尝试 INT4 量化或增加线程
3.  **多音色管理**：建立音色库，支持按角色切换
4.  **唤醒词**：添加离线唤醒词检测，避免持续录音
5.  **流式 ASR**：如 ASR 支持 streaming，可实现边说边识别
6.  **麦克风升级**：测试 card 2 DMIC 阵列，可能比 3.5mm 外接麦克风效果更好
7.  **搜索优化**：如果 Bing 频繁返回验证码，考虑换 Bing Web Search API（免费额度）
8.  **GPU 信息工具**：确认 Vulkan 后端的 GPU 监控方式（rocm-smi 可能不适用）
