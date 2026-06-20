# 语音助手与硬件监控播报系统需求文档

> **实现状态（2026-06-21）**
> - ✅ 监控播报链路：已上线运行（`monitor-broadcast.service` v6）
> - ✅ TTS 语音合成：Qwen3-TTS 1.7B 已部署（port 9900，音色 vivian）
> - ✅ 音频播放：ALSA card1 扬声器，流式预缓冲 + FIFO 管道
> - ✅ TTS 播放策略：流式预缓冲 80%，无非流式 fallback（生产版已移除 `_speak_wav`）
> - ⚠️ ASR：模型已部署（port 48091）但 API 格式未调通（`type: "audio"` 返回 400）
> - ❌ 语音助手链路：未开始开发

## 1. 项目概述
构建一个运行在推理机上的**纯 CPU 语音交互与监控播报系统**。系统包含两条独立但共享 TTS 资源的核心链路：
1.  **语音助手链路**：ASR 输入 -> LLM 队列调度 -> TTS 语音输出。
2.  **监控播报链路 (Kernel Log Speaker)**：独立线程实时监控核心硬件（358/278 GPU、CPU、内存），异常时实时 TTS 播报。

**核心约束**：ASR 和 TTS 均运行在纯 CPU 环境下，LLM (Qwen3.6 35B/27B) 运行在 GPU 上。需解决 LLM 忙碌时的缓存等待问题，以及 TTS 在 CPU 上的性能优化与模型降级策略。

---

## 2. 系统架构

```mermaid
graph TD
    User[用户语音] --> ASR[Qwen3-ASR (GGUF/CPU)]
    ASR --> Text[文本]
    
    subgraph LLM_Scheduler [LLM 调度器]
        Text --> Queue{LLM 状态检测}
        Queue -- 空闲 --> LLM[Qwen3.6 35B/27B (GPU)]
        Queue -- 忙碌 --> Cache[(缓存队列 FIFO)]
        Cache --> LLM
        LLM --> Reply[回复文本]
    end
    
    subgraph TTS_Engine [TTS 引擎 (CPU)]
        Reply --> TTS_1_7B[Qwen3-TTS 1.7B-Base (vivian)]
        TTS_1_7B --> Audio[语音输出]
    end
    
    subgraph Monitor_Thread [监控播报线程 (独立)]
        Kernel[Kernel Log / dmesg] --> Parser[日志解析]
        Hardware[GPU 358/278 / CPU / RAM] --> Metrics[指标采集]
        Parser --> Alert{阈值/关键字判断}
        Metrics --> Alert
        Alert -- 异常 --> TTS_Engine
    end
    
    Audio --> Speaker[扬声器/音频输出]
```

---

## 3. 功能需求

### 3.1 语音助手链路 (Voice Assistant Pipeline)

#### 3.1.1 ASR 输入
*   **模型**：Qwen3-ASR (GGUF 格式，已部署在 port 48091)。
*   **功能**：接收音频流/文件，输出识别文本。
*   **接口**：提供内部 API 或本地 Socket 接口供调度器调用。
*   ⚠️ **当前问题**：API 格式未调通，`type: "audio"` 返回 400 错误，需调试正确的 content type。

#### 3.1.2 LLM 调度与缓存
*   **状态检测**：在发送请求前，检测 LLM (35B/27B) 当前是否空闲。
    *   *实现建议*：通过 LLM 服务 API 的 `/health` 或自定义 `/status` 接口，或维护一个全局的 `Semaphore`/`Queue`。
*   **忙碌缓存**：
    *   当 LLM 忙碌时，ASR 输出的文本进入 **FIFO 缓存队列**。
    *   **永不超时丢弃**：队列无限等待，直到 LLM 空闲处理完毕，确保指令不丢失。
*   **并发控制**：确保同一时间只有一个用户请求占用 LLM（或根据 LLM 服务的并发能力配置）。

#### 3.1.3 TTS 语音合成
*   **推理底座**：Qwen3-TTS 服务（Python HTTP 服务，基于 llama.cpp GGUF 推理）。
    *   模型：Qwen3-TTS-12Hz-1.7B-Base，已部署为 systemd 用户服务（port 9900）。
    *   音色：vivian (中文女声)，volume=1.0，language=chinese。
    *   监控播报通过 HTTP 调用 `/v1/tts/stream` 端点获取流式 PCM 数据。
    *   ⚠️ 需求文档原文提到的「纯 C 语言推理引擎」方案未实际采用，当前为 llama.cpp GGUF + Python 服务。
*   **声音克隆 / 声音设计**：
    *   规划中的功能，当前未实现。TTS 服务支持相关 API 但监控播报未使用。
*   **流式输出**：
    *   `/v1/tts/stream` 端点已验证可用（HTTP 200, 49KB, 2.14s）。
    *   监控播报已采用流式预缓冲模式：估算音频时长 → 预填 80% 缓冲区 → 创建 FIFO 管道 → 启动 `aplay` 边生成边播放。
    *   生产版已移除非流式 fallback（`_speak_wav`），流式失败时跳过本次播报。

### 3.2 监控播报线程 (Kernel Log Speaker)

#### 3.2.1 监控对象（✅ 已实现）
*   **GPU (358/278 - AMD)**：
    *   温度 (Temperature)
    *   显存占用 (Memory Usage)
    *   利用率 (Utilization)
    *   **数据源**：`gpu-temp.log`（cron 5min 写入）+ `router.log` 日志文件。
    *   **提取指标**：从日志中实时提取显存峰值、温度告警、OOM (Out of Memory)、`Fatal`、`Error`（E 级别）、`Xid` 等关键字信息。
*   **CPU**：
    *   温度（通过 k10temp）
    *   负载 (Load Average)
*   **内存**：
    *   可用内存 / 交换分区使用率（`/proc/meminfo`）

#### 3.2.2 播报逻辑（✅ 已实现）
*   **独立线程**：与语音助手链路隔离，互不阻塞。已部署为 `monitor-broadcast.service`。
*   **双频率轮询**：
    *   快速轮询（180s）：模型切换 + 推理任务全生命周期（启动/prefill完成/生成里程碑/结束/空闲）。
    *   慢速轮询（300s）：硬件告警 + 日志 E/F 级别 + 日常播报（30min 间隔）。
*   **触发条件**：
    *   *阈值报警*：GPU 温度 > 80°C（警告）/ 90°C（严重），内存 > 80%（警告）/ 90%（严重），GPU 功耗 > 120W（警告）/ 130W（严重）。
    *   *关键字报警*：日志中出现 OOM、Xid、段错误、Vulkan 崩溃（`vk::DeviceLostError`）、Fatal、Error（E 级别）等。
*   **播报策略**：
    *   **去重**：同类严重告警 5 分钟内不重复播报。
    *   **优先级抢占**：severity ≥ 3 的严重告警直接插入 TTS 队列头部。
    *   **TTS 队列**：独立线程发送，避免播报中丢失消息。

---

## 4. 非功能需求

### 4.1 性能指标
*   **ASR 延迟**：< 500ms (GGUF CPU 推理)。
*   **LLM 响应**：取决于模型大小，调度器需保证队列不溢出。
*   **TTS RTF (CPU/APU)**：
    *   1.7B 实测：**RTF ~1.8-2.5**（纯 CPU 8 线程，llama.cpp GGUF 推理）。
    *   *注*：需求原文提到的「纯 C 引擎 + AVX 优化」方案未实际采用，当前为 llama.cpp GGUF 推理。
*   **首包延迟**：TTS 首包音频生成时间 < 1s。

### 4.2 资源管理
*   **128GB 统一内存**：
    *   推理机配备 128GB 统一内存。虽然大模型部署占用了大部分，但**空余内存依然充足**，足以容纳 TTS 模型加载。
    *   1.7B TTS 模型加载约需 12GB RAM。
    *   内存不再是瓶颈。
*   **并发**：支持至少 1 个用户对话 + 1 个监控播报并发。

### 4.3 可靠性
*   **异常恢复**：TTS 进程崩溃后自动重启。
*   **日志记录**：所有 ASR 文本、LLM 回复、TTS 生成耗时、监控报警均记录到本地日志文件。

---

## 5. 技术栈建议

| 组件 | 技术选型 | 备注 |
| :--- | :--- | :--- |
| **语言** | Python 3.10+ | 生态丰富 |
| **Web 框架** | FastAPI | 异步支持好，适合 API 服务 |
| **ASR** | llama.cpp / Qwen3-ASR GGUF | 现有部署 |
| **TTS** | llama.cpp GGUF (Qwen3-TTS-1.7B) | systemd 用户服务 port 9900，HTTP API 调用 |
| **LLM 客户端** | HTTP Client / vLLM API | 调用 35B/27B |
| **监控采集** | `psutil`, `tail -f`, `regex` | 读取 CPU/内存指标 + 实时解析大模型部署 `logs/` 目录日志 |
| **任务队列** | `asyncio.Queue` / `Redis` | 本地内存队列即可 |
| **音频播放** | `pyaudio` / `simpleaudio` | 本地播放或推流 |

---

## 6. 接口设计 (Draft)

### 6.1 语音助手 API
```http
POST /api/tts/chat
Content-Type: multipart/form-data

{
  "audio": <file>,          // 用户语音
  "ref_audio": <file|null>, // 可选：声音克隆参考音频
  "mode": "clone" | "design" // 模式
}

// Response: Streaming Audio (wav/pcm)
```

### 6.2 监控播报配置
```json
{
  "gpu_ids": [358, 278],
  "thresholds": {
    "gpu_temp": 85,
    "gpu_mem_pct": 95,
    "cpu_temp": 90
  },
  "keywords": ["Xid", "Critical", "Error"],
  "cooldown_seconds": 300
}
```

---

## 7. 部署与环境

*   **运行环境**：推理机 (Linux)。
*   **硬件**：
    *   CPU/APU：**AMD 395 APU** (高性能 CPU + 集成显卡，内存/显存共享)。
    *   GPU：358/278 (LLM 推理 + 监控对象)。
    *   RAM：**128GB 统一内存**（大模型部署占用大部分，空余内存充足，完全满足 TTS 模型加载需求）。
*   **依赖安装**：
    ```bash
    # TTS 服务已在推理机上部署为 systemd 用户服务
    # Python 调度器依赖
    pip install fastapi uvicorn psutil pyaudio
    ```

---

## 8. 后续优化方向
1.  **TTS 性能优化**：当前 RTF ~1.8-2.5（纯 CPU 8 线程），如需更低延迟可尝试 INT8/INT4 量化版本或增加线程数。
2.  **LLM 并发**：若 LLM 支持并发，调度器改为令牌桶限流。
3.  **多音色管理**：建立音色库，支持按角色切换播报音色。
4.  **纯 CPU 极致优化**：如后续需要，可探索 AVX-512 指令集适配与内存带宽优化，或切换到纯 C 推理引擎方案。
