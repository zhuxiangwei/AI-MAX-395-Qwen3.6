# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **[中文](./README.zh-CN.md)**

在 AMD Ryzen AI Max+ 395（Strix Halo）上使用 llama.cpp + Vulkan 部署 Qwen3.6 大语言模型，并通过 SSH 反向隧道 + Nginx HTTPS 将推理 API 暴露到公网。

---

## 性能基准

所有基准测试在 {your_machine}（AMD Ryzen AI Max+ 395，128 GB LPDDR5X，Radeon 8060S，llama.cpp b9692 Vulkan）上测量。速度数据来自 API `timings`（服务端统计，不含网络延迟）。生成速度包含 thinking tokens。

**基准测试环境：** CPU governor=performance，`processor.max_cstate=1`，`vm.swappiness=1`，`vm.overcommit_memory=1`，GTT 120GB，mlock=1。这些系统级优化相比默认的 powersave governor，能提升生成速度和 prefill 稳定性。

### 35B-A3B MoE（UD-Q8_K_XL，别名 `358`）

**语音助手专用模型。** MoE 每个 token 仅激活 3B/35B 参数。~50 t/s 生成速度。当前未配置 mmproj（视觉已禁用）。

**最优配置：F16 KV cache，UB=256。** UB=256 是当前生产配置（所有上下文长度下均稳定）。此前 UB=512 在 ≤128K 时更优（prefill +22~25%，TTFT -17~20%），但现已统一为 UB=256 用于所有模型。

**已排除：** UB=128（MTP 接受率 86%→65%，生成更慢）；UB≥1024（p256K prefill -44%，TTFT +80%）；Q8_0 KV（反量化开销 > 稀疏 KV 的带宽节省；所有 Q8_0 UB 均慢于 F16 UB=256）；UB≥2048（128K+ 时 Vulkan 崩溃）。

#### F16 KV UB=256（生产配置，b9692）

**按上下文长度的生成速度**（1468 个任务，cache-ram=65536）：

> ⚠️ 以下基准数据为历史数据，采集时 358 使用 cache-ram=65536 和不同配置。当前 358 已改为语音助手专用，cache-ram=4096。

| 上下文 | 任务数 | P50 (t/s) | 平均 (t/s) |
|---------|-------|-----------|------------|
| <4K | 1227 | 53.3 | 52.8 |
| 4–16K | 171 | 48.3 | 49.0 |
| 16–64K | 48 | 47.2 | 48.3 |
| 64–130K | 18 | 44.2 | 45.0 |
| 130–200K | 4 | 37.8 | 37.9 |

**按 prompt 长度的 prefill 速度**（1083 个任务，tokens ≥ 100，cache-ram=65536）：

> ⚠️ 同上，历史数据。

| Prompt | 任务数 | P50 (t/s) | 平均 (t/s) |
|--------|-------|-----------|------------|
| <1K | 625 | 240.8 | 251.6 |
| 1K–5K | 235 | 312.1 | 316.4 |
| 5K–10K | 102 | 290.4 | 290.5 |
| 10K–30K | 79 | 305.7 | 337.8 |
| 30K–60K | 17 | 347.7 | 356.6 |
| 60K–130K | 21 | 407.9 | 365.0 |
| 130K+ | 4 | 309.7 | 309.6 |

> 生产工作负载数据（F16 KV，UB=256，cache-ram=65536，llama.cpp b9692）。MTP 接受率：均值 86.8%，中位数 88.2%。~130K tokens 时 KV cache：~318 MiB（~2.4 KB/token，因 MoE 稀疏头）。观察到 checkpoint 驱逐（143 erased/225 created），表明 cache-ram 对单会话工作负载充足，但跨会话 cache 复用受 Qwen3 SWA 架构限制。
>
> **历史参考（b9625，201 个任务）：** 生成 P50：<4K=55.4，4–16K=50.3，16–64K=55.2，64–130K=48.1，130–200K=43.7。冷启动 prefill P50：<4K=453.8，4–16K=418.0，16–64K=313.9，64–130K=236.0，130–200K=222.9。b9625/b9692 间生成速度几乎相同；b9692 数据中 prefill P50 较低是因为更大样本中 cache 命中率更高（旧数据仅含冷启动）。
>
> **历史参考（F16 KV UB=512，已弃用）：** p128=56.7，p4K=56.7，p32K=50.1，p64K=46.7，p128K=38.0，p256K=28.4 t/s 生成；371–931 t/s prefill。UB=256/512 间生成速度几乎相同（±2 t/s）；UB 选择主要影响 prefill/TTFT。

### 27B Dense Q8（Q8_K_XL，别名 `278`）

Dense 模型 — 每个 token 激活全部 27B 参数。当前 Hermes 默认模型。

**配置：F16 KV + UB=256 + kv-unified=1 + cache-ram=32768 + slot-prompt-similarity=0.8。**

**已排除：** Q8_0 KV（KV 空间为 Q4_0 的 1.7–2 倍，无显著 prefill 优势）；Q4_0 KV（Vulkan 反量化开销抵消了带宽节省）；UB≥1024（长上下文 prefill 退化 11–34%）；UB≥2048（Vulkan 崩溃）。

#### F16 KV UB=256（当前配置，b9692）

**按响应长度的生成速度**（1001 个任务，decoded ≥ 100 tokens）：

| 响应长度 | 任务数 | 平均 (t/s) | P50 (t/s) |
|----------------|-------|----------|----------|
| <200 tokens | 237 | 11.6 | 11.7 |
| 200–500 | 395 | 11.7 | 11.8 |
| 500–1K | 178 | 10.7 | 10.5 |
| 1K–3K | 149 | 10.7 | 10.4 |
| 3K–5K | 23 | 10.7 | 10.8 |
| 5K+ | 19 | 10.0 | 10.0 |

**按上下文长度的生成速度**（1183 个任务）：

| 上下文 | 任务数 | P50 (t/s) | 平均 (t/s) |
|---------|-------|-----------|------------|
| <4K | 837 | 10.9 | 11.2 |
| 4–16K | 258 | 11.8 | 11.8 |
| 16–64K | 71 | 12.7 | 12.3 |
| 64–130K | 13 | 10.0 | 10.2 |
| 130–200K | 4 | 8.5 | 8.5 |

**按 prompt 长度的 prefill 速度**（1033 个任务，tokens ≥ 100）：

| Prompt 长度 | 任务数 | 平均 (t/s) | P50 (t/s) |
|--------------|-------|----------|----------|
| <1K | 397 | 60.5 | 38.1 |
| 1K–5K | 333 | 78.9 | 40.2 |
| 5K–10K | 147 | 84.9 | 54.0 |
| 10K–30K | 126 | 122.0 | 132.6 |
| 30K–60K | 13 | 91.1 | 93.2 |
| 60K–130K | 13 | 78.8 | 63.9 |
| 130K+ | 4 | 39.9 | 39.3 |

> † 生产工作负载数据（F16 KV，UB=256，cache-ram=32768，llama.cpp b9692，1001 生成 + 1033 prefill 任务）。生成速度包含 thinking tokens。短/中上下文：生成稳定在 11–13 t/s；长上下文（decoded 5K+）：8–10 t/s。Prefill 随 cache 命中率波动较大；短上下文（<5K）P50 较低是因为增量 cache 命中 prefill。16K+ 真实冷启动 prefill：150–226 t/s（中位数 ~200 t/s）。130K+：~45 t/s。MTP 接受率：均值 87.1%，中位数 89.2%。
>
> **历史参考（b9625，378 生成 + 413 prefill 任务）：** 按响应长度的生成均值：<200=11.7，200–500=12.0，500–1K=10.8，1K–3K=10.2，3K–5K=10.1，5K+=9.2。按 prompt 长度的 prefill 均值：<1K=50，1K–5K=71，5K–10K=79，10K–30K=132，30K–60K=62，60K–130K=91，130K+=46。b9625→b9692 间生成速度一致；更大样本中 prefill 呈现相似模式。
>
> **历史参考（Q8_0 KV UB=512，已弃用）：** p128=127.4，p4K=247.3，p32K=194.6，p64K=160.2，p128K=119.1，p256K=82.8 t/s prefill；生成 7.3–13.8 t/s。

### 跨模型对比（最优配置）

| Prompt | 35B UD-Q8 | 27B Q8 |
|--------|-----------|--------|
| p128 Gen | 56.7 | 13.8 |
| p4K Gen | 56.7 | 13.4 |
| p32K Gen | 50.1 | 12.5 |
| p64K Gen | 46.7 | 12.1 |
| p128K Gen | 38.0 | 10.0 |
| p256K Gen | 29.3† | 7.3 |
| p256K TTFT | 999s† | 3022s |

> 配置：35B Q8 = F16 KV（≤128K: UB=512，†256K: UB=256），27B Q8 = Q8_0 KV UB=512。生成速度包含 thinking tokens。

### 智力测试（35B MoE，MTP 已启用）

8 道题目，涵盖数学、逻辑、计算机科学和哲学。通过关键词匹配评分（每题最高 10 分，总分 80）。模型使用 F16 KV + UB=512 + MTP（`--spec-type draft-mtp --spec-draft-n-max 2`）。

> ⚠️ 智力测试在 358 仍使用 n=2 时进行。当前 278 和 358 均使用 n=3。278 MTP 接受率 ~87%，358 ~40%（MoE 架构接受率偏低）。

| 题目 | 358 (Q8) |
|----------|----------|
| 高斯求和（1+2+...+100） | 10/10 |
| 三段论有效性 | 4/10 |
| 二分查找复杂度 | 3/10 |
| 过河难题 | 10/10 |
| 量子纠缠 | 3/10 |
| 定积分 ∫₀¹x²dx | 3/10 |
| 说谎者悖论 | **10/10** |
| LRU cache 设计 | 10/10 |
| **总分** | **53/80** |
| 平均生成速度 | 57.3 t/s |

### 视觉测试（35B MoE + mmproj，MTP 已启用）

> ⚠️ **历史数据。** 当时使用 358 + mmproj 进行视觉测试。当前 358 已改为语音助手专用，未配置 mmproj。278 配置了 mmproj（Qwen3.6-27B-F16）。

模型使用 `mmproj-F16.gguf`（899 MB，qwen35moe 架构）。图片通过 OpenAI chat completions API 以 base64 编码发送。F16 KV + UB=512 + MTP。

| 图片 | Prompt tokens | 生成 (t/s) | MTP 接受率 | 耗时 |
|-------|-------------|-----------|----------------|---------|
| 婴儿睡觉（83 KB） | 939 | 51.2 | 50.9% | 18.3s |
| 户外照片（1.4 MB） | 2059 | 49.3 | 48.2% | 28.4s |
| 生日照片（2.8 MB） | 4034 | 53.5 | 55.2% | 39.9s |

> 视觉模式 MTP 接受率（48–57%）显著低于文本模式（60–70%），因为视觉 token 更难预测。模型能准确描述图片内容。

---

## 优化参数

### 关键决策与理由

| 决策 | 理由 |
|----------|-----------|
| 服务 = 服务级，INI = 模型级 | 清晰分离；修改模型参数无需触碰服务文件 |
| 统一 parallel=1，ctx=262144（278）/ 32768（358） | 简化配置；单用户工作负载；双模型模式 `--models-max 2`；278 使用 256K 上下文覆盖所有 prompt 长度，358 使用 32K 用于快速语音助手响应 |
| 统一 UB=256 | 所有模型使用 ubatch=256 以保证稳定性。278 的 UB=512 此前导致不稳定；统一为 UB=256。UB≥1024 导致长上下文 prefill 退化；UB≥2048 Vulkan 崩溃 |
| `cache-ram = 32768/4096`（INI 中按模型配置） | 按模型启用 prompt cache：278=32 GB（主模型，长对话），358=4 GB（语音助手专用）。双模型模式（`models-max 2`）需要保守的 cache-ram 以容纳两个模型。此前单模型模式下为 `49152/65536` |
| `reasoning-budget = 16384`（278）/ `0`（358） | 278：防止 thinking tokens 耗尽 KV cache/VRAM，同时允许更长的推理链。358：禁用推理，用于快速语音助手响应 |
| 不使用 `reasoning-format = none` | 该参数将 thinking 内容放入 `delta.content` 而非 `delta.reasoning_content`，导致 SSE 客户端（如 OpenClaw/QClaw）将 thinking 与实际响应混合，产生重复输出。不要添加此参数 |
| 所有模型：`parallel = 1` | 单用户工作负载不需要并发槽位；`parallel > 1` 浪费 KV cache 内存 |
| 服务：`--models-max 2` | 双模型模式：278 和 358 同时加载。Router 通过 LRU 自动切换。此前 `models-max 1`（单模型模式）以节省 GTT；切换回双模型模式并降低 cache-ram（32768/4096） |
| 27B Dense：仅 `parallel = 1` | 单用户工作负载不需要并发槽位（见已知问题） |
| `spec-draft-n-max = 3`（两个模型） | 278 和 358 均使用 n=3。278 MTP 接受率 ~87%，358 ~40%（MoE 架构接受率偏低） |
| `-t 8`（278）/ `-t 4`（358） | 278：与 `-t 16` 在全 GPU offload 下无差异；t=8 运行温度更低。358：较少线程以留出 CPU 余量给 278 |
| 不使用 `--no-mmap` | 无益处；`--mmap`（默认）+ `--mlock` 是最佳组合 |
| `-a Qwen3.6` | 设置 API 响应中的模型名；客户端校验 model 字段时需要 |
| `alias` 短名称 | 便捷路由，无需 symlink；别名和文件名均可使用 |
| 所有模型：F16 KV cache（默认） | INI 中不显式指定 `cache-type-k`/`cache-type-v` — llama-server 默认 F16。Q4_0 KV 此前在 278 上测试过（节省 ~50% 空间，prefill 相当），但当前未使用。不要在 Vulkan 后端启用量化 KV（见已知问题：MTP + Quantized KV） |
| `kv-unified = 1`（所有模型） | 统一所有槽位的 KV cache；Vulkan 后端 slot-save/restore 兼容性所需；同时绕过 Vulkan 统一内存上的 GGML_ASSERT 崩溃路径 |
| 系统：CPU governor=performance | 降低 GPU 命令提交延迟；提升生成速度和 TTFT 稳定性 |
| 系统：`processor.max_cstate=1` | 阻止 CPU 进入深度 C-state；减少 Vulkan 命令提交延迟尖峰 |
| 系统：`vm.swappiness=1`，`vm.overcommit_memory=1` | 最小化 swap 使用，防止 OOM killer 误报 |
| `sleep-idle-seconds` 按模型配置 | 278=1800s（30 分钟），358=600s（10 分钟）。模型空闲后自动卸载以释放 GTT。双模型模式下安全，因为一次只卸载一个模型 |

### 使用约束

| 约束 | 值 | 原因 |
|-----------|-------|--------|
| 所有模型：并发槽位 | 1（`parallel = 1`） | 单用户工作负载；`parallel > 1` 浪费 KV cache 内存 |
| 所有模型：最大上下文 | 256K（278：`ctx-size = 262144`），32K（358：`ctx-size = 32768`） | 278：统一上下文覆盖所有 prompt 长度。358：32K 足够语音助手对话 |
| 27B Dense：`parallel` | 仅 1 | 单用户工作负载无需并发（见已知问题） |
| 35B MoE：UB 约束 | UB=256（当前，所有上下文长度下稳定） | 278 和 358 统一为 UB=256 以保证稳定性；UB≥1024 在 ≥128K 时退化；UB≥2048 Vulkan 崩溃 |
| 27B Dense：UB 约束 | F16 KV UB=256（当前，278） | UB=512 此前导致不稳定；统一为 UB=256；UB≥2048 Vulkan 崩溃 |
| Thinking 模式 | 278：已启用（`reasoning-budget=16384`），358：已禁用（`reasoning-budget=0`） | 278：预算上限防止失控的 thinking。358：无推理，快速语音响应。客户端通过 `chat_template_kwargs.enable_thinking: false` 按请求禁用 thinking |
| 不使用 `reasoning-format=none` | 不要添加 | 导致 thinking 内容出现在 `delta.content` 而非 `delta.reasoning_content`，破坏 SSE 客户端解析（见已知问题） |
| `cache-ram` | 278=`32768`，358=`4096`（INI 中按模型配置） | 按模型角色设定 prompt cache 大小：278（主模型，32 GB）双模型模式；358（语音助手，4 GB）。此前单模型模式下为 `49152/65536` |
| `kv-unified` | 1（所有模型，在 INI 中设置） | 统一 KV cache；Vulkan slot-save/restore 所需；绕过统一内存上的 GGML_ASSERT 崩溃 |
| `sleep-idle-seconds` | 278=`1800`，358=`600`（INI 中按模型配置） | 空闲模型自动卸载以释放 GTT。双模型模式下安全——一次只卸载一个模型 |
| `b` 必须能被 `ub` 整除 | `n_batch % n_ubatch == 0` | llama.cpp 要求 |

### 参数分离原则

| 范围 | 位置 | 示例 |
|-------|-------|---------|
| **服务级** | `llama-router.service` ExecStart | `--host`，`--port`，`--api-key`，`--models-dir`，`--models-max`，`--models-preset`，`--timeout` |
| **模型级** | `router-preset.ini` 每个模型段 | `n-gpu-layers`，`ctx-size`，`ubatch-size`，`threads`，`alias`，`spec-type`，`mlock`，`numa`，... |

> 模型参数**仅**在 INI 中定义 — 不要在服务文件中重复。
>
> 完整的 Preset INI 和服务配置包含在下方各客户端章节中（Hermes / QClaw）。

---

## 部署指南

### 架构

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

**关键设计决策：**
- llama.cpp 仅绑定 `127.0.0.1:12345` — 不直接暴露到网络
- 云服务器**仅运行 Nginx**（端口 443）— 无应用代码
- SSH 反向隧道提供 NAT 穿透（家庭网络 → 云端）
- OpenAI 兼容 API 端点：`https://{your_domain}/v1/`
- **Router 模式** + 按模型 preset INI — 自动 LRU 模型切换
- **别名短名称**（278/358）便于模型选择

### 硬件

| 组件 | 规格 |
|-----------|--------------|
| 机器 | {your_machine} 迷你主机 |
| APU | AMD Ryzen AI Max+ 395（16C，SMT 已禁用） |
| 内存 | 128 GB LPDDR5X（256-bit，统一内存） |
| 存储 | 1 TB NVMe SSD |
| iGPU | Radeon 8060S（RDNA 3.5，40 CU，2040 MHz） |
| GTT（GPU 可访问内存） | 120 GB（内核参数 `amdgpu.gttsize=122880`） |

**内存带宽：** 256-bit × 8000 MT/s ÷ 8 = **256 GB/s** 理论值，~200 GB/s 实际值。Dense 模型受内存带宽限制。

### BIOS 配置

| 设置 | 值 | 用途 |
|---------|-------|---------|
| SMT（同步多线程） | **禁用** | LLM 推理受内存带宽限制；禁用 SMT 减少缓存争用，提升 KV cache 命中率 |
| GFX Workstation Support | **禁用** | 无头推理不需要；释放资源 |
| iGPU Mem Bar Configuration | **ResizableBAR** | 允许 GPU 访问全部系统内存以加载大模型权重 |
| UMA Version | **Non-Legacy** | ResizableBAR 和大统一内存分配所需 |
| Dedicated Graphics Memory | **0.5G** | 最小分配；模型权重通过 GTT 使用系统内存 |

> **为什么禁用 SMT？** 统一内存上的 LLM 推理受带宽限制（256 GB/s）。SMT 在共享 L3 缓存上增加线程争用，不提升带宽利用率。实际测试表明禁用 SMT 后 cache 命中率提升，延迟更稳定。

### GRUB 内核参数

**文件：** `/etc/default/grub`

```bash
GRUB_CMDLINE_LINUX_DEFAULT="amd_iommu=off amdgpu.gttsize=122880 processor.max_cstate=1"
```

- `amd_iommu=off` — 禁用 IOMMU，减少 GPU DMA 的内存转换开销
- `amdgpu.gttsize=122880` — 设置 GPU 可访问的系统内存（GTT）为 120 GB，允许 iGPU 访问几乎所有 128 GB RAM 用于模型权重
- `processor.max_cstate=1` — 阻止 CPU 进入深度 C-state，降低 Vulkan GPU 命令提交和 KV cache 操作的延迟

**应用：** `sudo update-grub && sudo reboot`

### 软件

| 组件 | 版本 / 详情 |
|-----------|-------------------|
| 推理机 OS | Ubuntu 26.04 LTS |
| 云服务器 OS | Ubuntu 24.04.4 LTS |
| llama.cpp | b9692（commit 35b1d5791，Vulkan 后端） |
| 编译选项 | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` |

> 当前版本 b9692（commit 35b1d5791，2026-06-18）。Commit `6c4cbdc70`（"server: MTP layer kv-cache should respect draft type ctk"）仍然存在，但当前部署使用默认 F16 KV cache（INI 中无显式 `cache-type-k`/`cache-type-v`），因此此 bug **不会触发**。仅在重新启用量化 KV（如 `q8_0`、`q4_0`）时才会出现。在上游修复前不要在 Vulkan 后端启用量化 KV。

| Vulkan 运行时 | 1.4.341 |
| API 协议 | OpenAI 兼容（`/v1/chat/completions`，`/v1/models`） |

**编译 llama.cpp：**

```bash
cd ~/llama.cpp
git pull origin master                    # update source
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
| llama-server 二进制 | `$HOME/llama.cpp/build/bin/llama-server` |
| Router preset（所有模型） | `$HOME/model/router-preset.ini` |

### 模型清单

Router 模式从 `$HOME/model/` 提供所有模型。双模型模式（`--models-max 2`）：278 和 358 同时加载；Router 通过 LRU 自动切换。每个模型有一个**别名**用于短名称路由。

**模型来源（HuggingFace）：**

| 来源 | 简称 | 模型 | 描述 |
|--------|-------|--------|-------------|
| [unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | **UD-35B** | 358 | 35B MoE 的 Unsloth Dynamic 量化 |
| [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) | **UD-27B** | 278 | 27B Dense 的 Unsloth Dynamic 量化 |

| 别名 | 文件 | 来源 | 量化 | 架构 | 大小 | 激活参数 | 角色 |
|-------|------|--------|-------|------|------|---------------|------|
| **358** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | UD-35B | UD-Q8_K_XL | **MoE** | ~37 GB | 3B | 语音助手专用 |
| **278** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | UD-27B | UD-Q8_K_XL | Dense | ~33 GB | 27B | 主模型（Hermes 默认 + fallback，支持视觉） |

> **别名命名规则：** UD 模型使用 3 位数字 = 模型大小 + 量化级别（如 `358` = 35B Q8，`278` = 27B Q8）。别名和完整文件名在 API 请求中均可使用。
>
> **部署模式：** 双模型模式（`models-max 2`）：278 和 358 同时加载。每模型 `cache-ram` 限制（278=32768，358=4096）按双模型 GTT 预算设定。GTT 120GB + mlock=1。每模型 `sleep-idle-seconds`（278=1800，358=600）用于自动卸载。278 通常常驻（Hermes/QClaw 持续使用）。

### 1. 云端 Nginx 配置

**文件：** `/etc/nginx/sites-enabled/default`（LLM 相关配置段）

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

**要点：**
- `/v1/` 代理到 `127.0.0.1:8080`（SSH 隧道 → 推理服务器）
- `client_max_body_size 64m` 适配长 prompt
- SSE 需要 `proxy_buffering off` + `gzip off`
- Nginx 超时 3600s；Hermes 侧超时 7200s（Hermes 自行处理重连）

**应用：** `sudo nginx -t && sudo systemctl reload nginx`

### 2. 云端 SSH 服务器

**文件：** `/etc/ssh/sshd_config`

```sshd_config
AllowTcpForwarding yes
ClientAliveInterval 60
ClientAliveCountMax 3
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

> ⚠️ 检查 `/etc/ssh/sshd_config.d/` 中的 drop-in 文件，可能覆盖主配置。

**应用：** `sudo systemctl restart ssh`

**验证：** `sudo sshd -T | grep -E "allowtcpforwarding|clientaliveinterval|passwordauthentication|pubkeyauthentication"`

### 3. SSH 反向隧道（systemd）

**文件：** `~/.config/systemd/user/llama-tunnel.service`

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
systemctl --user enable llama-tunnel
systemctl --user start llama-tunnel
loginctl enable-linger
```

### 4. Swap 配置（Ubuntu）

```bash
# Create 32 GB swap file
sudo fallocate -l 32G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

> 32 GB swap 为模型冷加载内存尖峰提供安全余量。模型常驻后，实际 swap 使用极少（观察约 17 MB）。

### 5. 硬件温度监控

FEVM FAEX1 迷你主机主板（ITE 0x5571 芯片）没有上游 Linux `lm-sensors` 驱动。硬件温度通过 hwmon 子系统获取多个传感器：GPU（amdgpu hwmon7）、CPU（k10temp hwmon4）、NVMe（hwmon2）、网卡 r8169（hwmon3）、网卡 eno1（hwmon5）、WiFi（hwmon6）。

**监控脚本：** `~/scripts/hw-temp.sh`

```bash
#!/bin/bash
# 硬件温度/负载综合日志
# 记录 GPU(amdgpu) / CPU(k10temp) / NVMe / 网卡 等温度 + GPU 负载

INTERVAL=60
LOGFILE="/home/zxw/logs/hw-temp.log"
mkdir -p "$(dirname "$LOGFILE")"

echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] hw-temp started" >> "$LOGFILE"

while true; do
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    
    # GPU 负载
    busy=$(cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1)
    
    # 各传感器温度
    gpu_edge=$(cat /sys/class/hwmon/hwmon7/temp1_input 2>/dev/null)
    cpu_tctl=$(cat /sys/class/hwmon/hwmon4/temp1_input 2>/dev/null)
    nvme=$(cat /sys/class/hwmon/hwmon2/temp1_input 2>/dev/null)
    nic_r8169=$(cat /sys/class/hwmon/hwmon3/temp1_input 2>/dev/null)
    nic_eno1=$(cat /sys/class/hwmon/hwmon5/temp1_input 2>/dev/null)
    wifi=$(cat /sys/class/hwmon/hwmon6/temp1_input 2>/dev/null)
    
    # 转换为 °C
    gpu_edge=${gpu_edge:+$((gpu_edge / 1000))}
    cpu_tctl=${cpu_tctl:+$((cpu_tctl / 1000))}
    nvme=${nvme:+$((nvme / 1000))}
    nic_r8169=${nic_r8169:+$((nic_r8169 / 1000))}
    nic_eno1=${nic_eno1:+$((nic_eno1 / 1000))}
    wifi=${wifi:+$((wifi / 1000))}
    
    echo "$ts gpu_busy=${busy:-0}% gpu=${gpu_edge:-NA}°C cpu=${cpu_tctl:-NA}°C nvme=${nvme:-NA}°C r8169=${nic_r8169:-NA}°C eno1=${nic_eno1:-NA}°C wifi=${wifi:-NA}°C" >> "$LOGFILE"
    sleep "$INTERVAL"
done
```

**systemd 用户服务：** `~/.config/systemd/user/hw-temp.service`

```ini
[Unit]
Description=Hardware Temperature Logger

[Service]
Type=simple
ExecStart=/bin/bash -c '/home/$USER/scripts/hw-temp.sh'
Restart=on-failure
RestartSec=10
```

**设置：**

```bash
mkdir -p ~/scripts ~/logs
chmod +x ~/scripts/hw-temp.sh
systemctl --user daemon-reload
systemctl --user enable --now hw-temp.service
```

**示例输出：**
```
2026-06-24 18:11:42 gpu_busy=100% gpu=71°C cpu=70°C nvme=41°C r8169=51°C eno1=55°C wifi=47°C
```

> **注意：** 监控广播系统读取 `hw-temp.log` 获取硬件告警。GPU 温度 warn=80°C，crit=90°C。CPU 温度 warn=80°C，crit=90°C。满载推理时观察范围：GPU 78–83°C，CPU 74–82°C（TjMax 100°C）。

### 6. Preset INI（按模型参数）

**文件：** `~/model/router-preset.ini`

```ini
; Router preset - 所有模型由 Router 统一管理
; models-max=2: 278和358可同时加载
;
; cache-idle-slots: 全部开启（默认），空闲KV cache存入cache-ram释放显存
; timeout: HTTP 并发等待窗口

[Qwen3.6-27B-UD-Q8_K_XL]                    # alias: 278 — primary (Hermes default + fallback)
n-gpu-layers = 99
flash-attn = auto
kv-unified = 1
parallel = 1
ctx-size = 262144
batch-size = 4096
ubatch-size = 256
spec-type = draft-mtp
spec-draft-n-max = 3
cache-ram = 32768
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

[Qwen3.6-35B-A3B-UD-Q8_K_XL]                # alias: 358 — auxiliary (voice assistant, fast response)
n-gpu-layers = 99
flash-attn = auto
kv-unified = 1
parallel = 1
ctx-size = 32768
batch-size = 4096
ubatch-size = 256
spec-type = draft-mtp
spec-draft-n-max = 3
cache-ram = 4096
mlock = 1
numa = distribute
reasoning-budget = 0
threads = 4
temp = 0.6
top-p = 0.95
top-k = 20
presence-penalty = 0.0
min-p = 0.0
slot-prompt-similarity = 0.8
sleep-idle-seconds = 600
alias = 358
timeout = 600
```

**修改模型参数：** 编辑 INI 文件 → 重启 llama-server（通过 `systemctl --user restart llama-router` 或手动重启）

### 7. 推理服务（systemd）

**文件：** `~/.config/systemd/user/llama-router.service`（用户级，无需 sudo）

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

```bash
systemctl --user daemon-reload
systemctl --user enable llama-router
systemctl --user start llama-router
loginctl enable-linger   # survive logout
```

> 该服务使用包装脚本（`llama-router.sh`）处理 SIGTERM 清理和日志输出。包装脚本运行 `llama-server` 时使用 `--models-max 2`（双模型模式，278 + 358 同时加载）和 `--models-preset`（从 INI 读取按模型参数）。模型参数（cache-ram、ubatch 等）在 preset INI 中定义，不在服务文件中。GTT 120GB + mlock=1 确保模型权重驻留物理内存。`LimitMEMLOCK=infinity` 允许 mlock 全部模型权重。`TimeoutStartSec=300` 防止 systemd 在长时间模型加载时杀死服务。无 slot-checkpoint。

### 8. 模型切换

客户端在 API 请求中指定 `model` 字段。**别名短名称**和**完整文件名**均可使用。Router 在两个常驻模型间通过 LRU 自动切换：

```bash
# Using alias (recommended)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "278", ...}'   # primary model (Hermes default)

# Using full filename (also works)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "Qwen3.6-35B-A3B-UD-Q8_K_XL", ...}'

# Switch to auxiliary model (voice assistant, fast response)
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "358", ...}'
```

### 客户端集成

#### Hermes Agent

[Hermes](https://github.com/nicobailon/hermes-agent) v0.17.0 — 终端 AI agent，支持 TUI、oneshot 模式、多平台 Gateway、MCP、Skills 和 cron 调度。

**安装路径：** WSL Ubuntu 26.04 上的 `~/.hermes/`

**配置文件：** `~/.hermes/config.yaml` — 单机部署，278 为默认模型，辅助任务均使用 278。

| 配置项 | 值 |
|---|---|
| **model.default** | `278`（27B Dense） |
| **providers.models** | `278` |
| **supports_vision** | `true`（278 配置了 mmproj，支持视觉能力） |
| **auxiliary tasks** | 全部 → `278`，辅助任务关闭 thinking |
| **fallback_model** | `{provider: local-llm, model: '278'}` |

**关键配置：**
- Provider：`local-llm` → `https://{your_domain}/v1`
- `key_env: DASHENZHIYAN_API_KEY`（设置在 `~/.hermes/.env` 中）
- `context_length: 262144`，`max_output_tokens: 32768`，`max_tokens: 32768`
- `request_timeout_seconds: 7200`，`stale_timeout_seconds: 7200`（与全链路超时对齐）
- `agent.gateway_timeout: 7200`，`approvals.timeout: 7200`，`approvals.gateway_timeout: 7200`
- `chat_template_kwargs.enable_thinking: true`（主模型），`false`（辅助模型）
- `compression: threshold=0.80, target_ratio=0.30, protect_last_n=20`
- `streaming.enabled: true`（gateway bot 流式传输）
- `approvals.mode: auto`

**环境变量覆盖**（`~/.hermes/.env`）：
```bash
HERMES_STREAM_READ_TIMEOUT=7200   # override hardcoded 120s default
HERMES_STREAM_STALE_TIMEOUT=7200  # override hardcoded 180s default
```

**⚠️ 注意事项：**
- `providers` 键必须为 `local-llm`（v0.17.0），不是 `custom:local-llm`（v0.15.1）。不匹配 → 超时回退到 120s
- `auxiliary.vision.base_url` 必须显式设置（空字符串 → 视觉任务 RuntimeError）
- `fallback_model` 必须为字典 `{provider: ..., model: ...}`，不能为纯字符串
- `yaml.dump` 可能丢弃纯字符串值（如 `fallback_model: '278'` → 空）；重写后需验证

**使用：**
```bash
wsl                                    # 进入 WSL
hermes                                 # TUI 模式（交互式）
hermes -z 'quick question'             # oneshot 模式
```

**TUI 命令：** `/skills` 列出技能，`/help` 所有命令，`Ctrl+C` 中断，`Ctrl+D` 或 `/exit` 退出。

#### opencode（WSL）

[opencode](https://opencode.ai) — 基于终端的 AI 编码 agent，配置为使用本地推理服务器。

**配置文件：** `~/.config/opencode/opencode.jsonc`

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

**要点：**
- 主模型（`model`）：278（27B Dense），启用 reasoning
- 辅助模型（`small_model`）：278（与主模型相同，复用已加载模型，零延迟）
- context=262144，output=32768
- 超时：7200000ms（7200s），与 Hermes 和 llama-server 对齐

#### QClaw

QClaw（OpenClaw）— 个人 AI 助手，支持多渠道（微信、QQ、网页聊天）。

- **Provider：** `qclaw` → `http://127.0.0.1:19000/proxy/llm`（云端代理，含模型路由）
- **默认模型：** `qclaw/pool-glm-5.1`（云端代理，不直接访问推理服务器）
- **渠道：** `wechat-access`（QQ），`openclaw-weixin`（微信本地）

#### TTS 语音合成服务

Qwen3-TTS 1.7B CustomVoice 模型纯 CPU 运行，为监控广播系统和语音助手提供语音输出。支持 9 种预置音色（含中文女声 vivian/serena）。

| 项目 | 详情 |
|------|---------|
| 模型 | Qwen3-TTS-12Hz-1.7B-CustomVoice |
| 路径 | `/home/zxw/model-tts/Qwen3-TTS-12Hz-1.7B-CustomVoice/` |
| 服务 | systemd 用户服务 `qwen3-tts.service`（端口 12348，已启用） |
| 启动脚本 | `/home/zxw/scripts/qwen3-tts.sh` |
| 启动参数 | `-S`（非流式模式） |
| 性能 | RTF ~1.8-2.5（纯 CPU 8 线程），短文本 ~2.9s |
| 内存 | ~3.2 GB |

**预置音色：**

| Speaker | 语言 | 性别 |
|---------|------|------|
| vivian | 中文 | 女 |
| serena | 中文 | 女 |
| ryan | 中文 | 男（默认） |
| uncle_fu | 中文 | 男 |
| dylan | 中文 | 男 |
| eric | 中文 | 男 |
| ono_anna | 日语 | 女 |
| sohee | 韩语 | 女 |
| jessica | 英语 | 女 |

> ⚠️ 之前使用 Base 模型时 `spk_id` 为空，speaker 参数被忽略，所有输出均为默认男声。CustomVoice 模型包含预置 speaker 映射，speaker 参数生效。Base 模型保留在 `/home/zxw/model-tts/Qwen3-TTS-12Hz-1.7B-Base/` 但不再加载。

**API 端点：**

| 端点 | 方法 | 描述 |
|----------|--------|-------------|
| `/v1/tts` | POST | 非流式合成，返回完整 WAV |
| `/v1/audio/speech` | POST | OpenAI 兼容接口 |

**请求示例：**

```bash
curl -s -X POST http://127.0.0.1:12348/v1/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"监控播报系统已上线","speaker":"vivian","language":"chinese","seed":42}' \
  -o /tmp/tts_out.wav
```

**音频播放：**

推理机内置扬声器（card1 ALC245 Analog），通过 ALSA 播放：

```bash
# Play via dmix (shared, non-blocking)
aplay -q -D default /tmp/tts_out.wav
```

**ALSA 配置：** `/etc/asound.conf` 配置 dmix（播放共享）和 dsnoop（录音共享），允许多进程同时访问音频设备。

> ⚠️ 通过 SSH 播放音频时不要使用 `< /dev/null` 重定向（会挂起会话）。使用 `aplay -q -D default` 走 dmix 共享。

#### Qwen3-ASR 语音识别服务

Qwen3-ASR 1.7B 模型纯 CPU 运行，为语音助手管道提供语音转文字功能。

| 项目 | 详情 |
|------|---------|
| 模型 | `Qwen3-ASR-1.7B-Q8_0.gguf`（2.1 GB） |
| mmproj | `mmproj-Qwen3-ASR-1.7B-Q8_0.gguf`（340 MB） |
| 服务 | systemd 用户服务 `qwen3-asr.service`（端口 12347，已启用，运行中） |
| 启动脚本 | `/home/zxw/scripts/qwen3-asr.sh` |
| 推理 | 纯 CPU（`n-gpu-layers=0`），不占用 GPU |
| 上下文 | `ctx-size=65536`（模型完整训练上下文） |
| 线程 | 8 |
| 超时 | 600s |
| 性能 | prompt eval 199.95 t/s，eval 36.29 t/s |
| API | OpenAI 兼容（llama-server） |

**服务文件：** `~/.config/systemd/user/qwen3-asr.service`

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

**启动脚本：** `/home/zxw/scripts/qwen3-asr.sh`

```bash
#!/bin/bash
# ASR 纯 CPU 推理（不占用 GPU，避免影响大模型）
# ctx-size 65536 = 模型完整训练上下文

LOGDIR="/home/zxw/logs/llama"
BINDIR="/home/zxw/llama.cpp/build/bin"
SERVER="$BINDIR/llama-server"
MODEL="/home/zxw/model-asr/Qwen3-ASR-1.7B-Q8_0.gguf"
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
  --parallel 1 \
  --no-cache-idle-slots \
  --cache-ram 0 \
  --timeout 600 \
  >> "$LOGDIR/asr.log" 2>&1
```

> ASR 完全在 CPU 上运行，避免与 GPU 大模型推理竞争资源。65536 上下文覆盖模型完整训练上下文长度。

### ai-station-angle

应用套件位于仓库 `ai-station-angle/` 目录，为推理站提供监控广播和语音助手能力。

**文件：**
- `monitor-broadcast.py` — 监控广播系统脚本
- `voice_assistant.py` — 语音助手主程序（Mic → VAD → ASR → LLM → TTS → 播放）
- `mic_recorder.py` — 麦克风录音模块（ALSA + 能量 VAD）
- `asr_module.py` — ASR 语音识别模块（port 12347）
- `llm_module.py` — LLM 对话模块（Router port 12345，别名 358 含 prewarm，tool calling）
- `tts_module.py` — TTS 语音合成模块（port 12348）
- `tools.py` — 工具定义与执行（6 个工具：时间/系统信息/搜索/天气/网页/计算器）
- `voice_assistant_monitor_requirements.md` — 需求文档

**监控广播系统（v8，生产版）：**

自动化监控和 TTS 广播服务，实时监控 LLM 推理状态和硬件健康。读取 `hw-temp.log` 获取全面硬件监控（GPU、CPU、NVMe、网卡、WiFi 温度）。

| 项目 | 详情 |
|------|---------|
| 脚本 | `ai-station-angle/monitor-broadcast.py` |
| 服务 | systemd 用户服务 `monitor-broadcast.service`（已启用，Restart=on-failure） |
| 状态文件 | `~/.config/monitor-broadcast/state.json` |
| 硬件日志 | `/home/zxw/logs/hw-temp.log`（由 `hw-temp.sh` 通过 `hw-temp.service` 生成） |

**双频轮询架构：**

| 轮询类型 | 间隔 | 监控内容 |
|-----------|----------|----------|
| 快速轮询 | 180s | 模型切换、推理任务生命周期（启动/prefill 完成/生成里程碑/结束/空闲） |
| 慢速轮询 | 300s | 硬件告警（GPU/CPU 温度、系统 RAM）、日志 E/F 级别条目、每日广播 |

**每日广播间隔：** 30 分钟。

**告警阈值：**

| 指标 | WARN | CRIT |
|--------|------|------|
| GPU 温度 | 80°C | 90°C |
| CPU 温度 | 80°C | 90°C |
| 内存使用 | 80% | 90% |

**日志告警关键词：** OOM、Xid、segfault、Vulkan crash（`vk::DeviceLostError`）、子进程崩溃、Fatal、Error。严重告警 5 分钟去重。

**TTS 广播队列：**
- 队列上限：3 条（溢出直接丢弃新消息）
- CRIT 告警（severity ≥ 3）插队到队首
- 播放：非流式 WAV 模式（默认，稳定）— TTS 合成完整 WAV 后由 `aplay` 播放
- 流式预缓冲模式可通过 `TTS_USE_STREAM = True` 开关启用

**系统音量：** ALSA Master 100%，TTS 引擎不管理音量。

**核心约束：** ASR 和 TTS 纯 CPU 运行；LLM 在 GPU 上运行。确保语音处理不会与 LLM 推理争抢 GPU 资源。

**语音助手管道（已实现）：** 麦克风 → VAD → ASR（port 12347）→ LLM（Router port 12345，35B-A3B 别名 358 含 prewarm）→ TTS（port 12348）→ 扬声器。完整链路代码完成，待联调测试。

**监控广播管道（已上线）：** 独立线程监控硬件（GPU/CPU/RAM）+ 日志告警 → TTS 广播。

**状态持久化：** `~/.config/monitor-broadcast/state.json` 存储文件 offset、告警冷却、当前模型/端口、播报元数据。瞬态状态（`_active_task`、`_last_gen_milestone`）仅运行时有效，不持久化。

### 验证清单

- [ ] 云端 Nginx 配置已更新（含 `/v1/` 和 `/health` 端点）
- [ ] 云端 SSL 证书已配置
- [ ] 云端 `sshd_config` 允许 TCP 转发和保活
- [ ] 推理机已配置 SSH 密钥免密登录云端
- [ ] `llama-tunnel.service` 已创建且**活跃**
- [ ] 云端：`ss -tlnp | grep 8080` 显示隧道监听中
- [ ] `llama-router.service` 已创建且**活跃**（仅服务级参数，`--models-max 2`）
- [ ] `~/model/router-preset.ini` 已配置按模型参数 + 别名（仅 278/358）
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回含别名的模型列表
- [ ] 双模型模式：278 和 358 已加载；Router 通过 LRU 自动切换
- [ ] 每模型 `sleep-idle-seconds` 已配置（278=1800，358=600）
- [ ] 外部：`curl https://{your_domain}/health` 返回 `OK`
- [ ] 硬件温度监控：`systemctl --user status hw-temp.service` 活跃
- [ ] 硬件温度日志：`cat ~/logs/hw-temp.log` 每 60 秒有条目
- [ ] ASR 服务：`systemctl --user status qwen3-asr.service` 活跃
- [ ] TTS 服务：`systemctl --user status qwen3-tts.service` 活跃
- [ ] 语音助手服务：相关服务活跃
- [ ] 别名路由：`curl -d '{"model":"358",...}'`、`curl -d '{"model":"278",...}'` 均可工作

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

## 已知问题

### `reasoning-format=none` 导致 SSE 客户端重复输出

**状态：** 已修复 — 已从 `router-preset.ini` 中移除

**受影响客户端：** OpenClaw/QClaw 及任何使用 `@mariozechner/pi-ai` OpenAI completions 解析器的 SSE 客户端。

**症状：** 助手响应包含重复内容 — thinking 过程和实际回答混在一起，在下一轮中重复出现。

**根本原因：** `reasoning-format=none` 指示 llama-server 将 thinking 内容放入 `delta.content`（而非标准的 `delta.reasoning_content` 字段）。OpenAI completions SSE 解析器将所有 `delta.content` 视为普通文本，生成一个同时包含 thinking 和实际响应的文本块。存入对话历史后，下一轮看到 thinking 内容，导致模型重复。

**验证：** 不使用 `reasoning-format=none` 时，SSE chunk 正确分离：
- Thinking → `delta.reasoning_content` → 解析器创建独立 `thinking` 块
- 响应 → `delta.content` → 解析器创建 `text` 块

**修复：** 从 `router-preset.ini` 的所有模型段中移除 `reasoning-format = none`。Thinking 将使用标准的 `reasoning_content` 字段。

---

### MTP + 量化 KV cache 导致 Vulkan DeviceLost

**状态：** 待修复 — 当前使用 F16 KV 规避，上游未修复

Vulkan + 量化 KV + MTP 在长上下文（≥64K）下触发 `vk::DeviceLostError`，导致 llama-server 槽位进程崩溃。当前部署使用默认 F16 KV cache（INI 中无显式 `cache-type-k`/`cache-type-v`），因此此问题**当前不会触发**。在上游修复前不要在 Vulkan 后端启用量化 KV。

---

### Hermes 视觉 `base_url: ''` 导致 RuntimeError

**状态：** 已解决 — 将 `auxiliary.vision.base_url` 设为 `https://{your_domain}/v1`

**受影响场景：** Hermes 配置中 `auxiliary.vision.base_url` 为空字符串（`''`）。

**症状：** 视觉请求失败，报 `RuntimeError: No LLM provider configured for task=vision`。

**根本原因链：**
1. `resolve_vision_provider_client()` 先检查 `base_url` — 空字符串为 falsy → 跳过显式分支
2. `requested="custom:local-llm"` ≠ `"auto"` → 跳过自动检测分支
3. 回退到 `_get_cached_client(is_vision=True)` → `resolve_provider_client()` 无法解析 `custom:*` + `is_vision=True` → 返回 None
4. `None` → RuntimeError

**关键洞察：** 非视觉辅助任务（web_extract、compression 等）在 `base_url` 为空时正常工作，因为其代码路径使用 `_get_cached_client(is_vision=False)`，能正确解析命名 provider。仅视觉路径有额外的 `base_url` 分支。

**修复：** 显式设置 `auxiliary.vision.base_url` 为 `https://{your_domain}/v1`。即使 provider 已定义 `base_url`，视觉解析路径不会回退到 provider 的 `base_url`。

**警告：** 修改 Hermes 配置后（包括 `yaml.dump` 重写），始终验证 `auxiliary.vision.base_url` 不为空。

---

### Hermes Providers 键不匹配导致 120s 超时回退

**状态：** 已修复 — v0.17.0 使用 providers 键 `local-llm`（无 `custom:` 前缀）。

**受影响场景：** Hermes 配置中 `model.provider = "custom:local-llm"`，但 `providers` 字典键为 `local-llm`（缺少 `custom:` 前缀）。

**症状：** 长上下文请求（>120K tokens）在 ~120s 处一致失败，即使 `request_timeout_seconds` 设为 7200。短请求正常，导致问题难以诊断。

**根本原因链：**
1. Hermes 调用 `get_provider_request_timeout("custom:local-llm", "278")` 查找超时
2. 函数按完整键（含 `custom:` 前缀）搜索 `providers` 字典
3. 如果键为 `local-llm` 而非 `custom:local-llm`，查找返回 `None`
4. `None` → 回退到硬编码的 `HERMES_STREAM_READ_TIMEOUT = 120s`
5. 同理，`get_provider_stale_timeout()` 返回 `None` → 回退到 `HERMES_STREAM_STALE_TIMEOUT = 180s`
6. 131K-token prefill 在 278 模型上耗时 ~1103s → 在 120s 处被杀

**修复：** 确保 `providers` 字典键与 `model.provider` 完全匹配。验证方式：
```python
get_provider_request_timeout("custom:local-llm", "278")  # should return 7200.0, not None
get_provider_stale_timeout("custom:local-llm", "278")     # should return 7200.0, not None
```

**警告：** `providers` 键**必须与** `model.provider` 完全匹配，包括 `custom:` 前缀。Hermes 文档中未记录此点，容易忽略。

---

*测试环境：{your_machine} · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9692 Vulkan · 2026-06-24*
