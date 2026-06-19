# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 对外提供推理 API。

---

## 性能基准

所有基准测试均在 {your_machine} (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9692 Vulkan) 上完成。速度通过 API `timings` 测量（服务端，排除网络延迟）。Gen 速度含 thinking tokens。

**基准测试环境：** CPU governor=performance，`processor.max_cstate=1`，`vm.swappiness=1`，`vm.overcommit_memory=1`，GTT 120GB，mlock=1。这些系统级优化相比默认 powersave governor 改善了 gen 速度和 prefill 稳定性。

### 35B-A3B MoE (UD-Q8_K_XL, 别名 `358`)

**辅助模型——Hermes 辅助任务（视觉、压缩等）。** MoE 每 token 仅激活 35B 中的 3B 参数。~50 t/s 生成速度，支持视觉。

**最优配置：F16 KV cache，UB=256。** UB=256 是当前生产配置（所有上下文长度稳定）。此前 UB=512 在 ≤128K 更优（prefill +22~25%，TTFT -17~20%），但现已统一 UB=256。

**已排除：** UB=128（MTP 86%→65%，gen 更慢）；UB≥1024（p256K prefill -44%，TTFT +80%）；Q8_0 KV（反量化开销 > 稀疏 KV 带宽节省；所有 Q8_0 UB 均不如 F16 UB=256）；UB≥2048（Vulkan 崩溃 128K+）。

#### F16 KV UB=256（生产配置，b9692）

**生成速度（按上下文长度，1468 任务，cache-ram=65536）：**

| 上下文 | 任务数 | P50 (t/s) | 均值 (t/s) |
|--------|--------|-----------|------------|
| <4K | 1227 | 53.3 | 52.8 |
| 4–16K | 171 | 48.3 | 49.0 |
| 16–64K | 48 | 47.2 | 48.3 |
| 64–130K | 18 | 44.2 | 45.0 |
| 130–200K | 4 | 37.8 | 37.9 |

**Prefill 速度（按提示长度，1083 任务，tokens ≥ 100，cache-ram=65536）：**

| 提示长度 | 任务数 | P50 (t/s) | 均值 (t/s) |
|----------|--------|-----------|------------|
| <1K | 625 | 240.8 | 251.6 |
| 1K–5K | 235 | 312.1 | 316.4 |
| 5K–10K | 102 | 290.4 | 290.5 |
| 10K–30K | 79 | 305.7 | 337.8 |
| 30K–60K | 17 | 347.7 | 356.6 |
| 60K–130K | 21 | 407.9 | 365.0 |
| 130K+ | 4 | 309.7 | 309.6 |

> 生产日志数据（F16 KV，UB=256，cache-ram=65536，llama.cpp b9692）。MTP 接受率：均值 86.8%，中位数 88.2%。~130K token 上下文 KV 缓存约 318 MiB（~2.4 KB/token，因 MoE 稀疏头数少）。Checkpoint 驱逐观察（143 次/225 次创建），表明 cache-ram 对单对话工作负载充足，但跨对话缓存复用受 Qwen3 SWA 架构限制。
>
> **历史参考（b9625，201 任务）：** Gen P50: <4K=55.4, 4–16K=50.3, 16–64K=55.2, 64–130K=48.1, 130–200K=43.7。冷启动 prefill P50: <4K=453.8, 4–16K=418.0, 16–64K=313.9, 64–130K=236.0, 130–200K=222.9。Gen 速度在 b9625/b9692 间基本一致；b9692 prefill P50 偏低因样本更大且含 cache-hit（旧数据仅冷启动）。
>
> **历史参考（F16 KV UB=512，已弃用）：** p128=56.7, p4K=56.7, p32K=50.1, p64K=46.7, p128K=38.0, p256K=28.4 t/s gen；371–931 t/s prefill。Gen 速度在 UB=256/512 间几乎相同（±2 t/s）；UB 选择主要影响 prefill/TTFT。

### 35B-A3B MoE APEX I-Quality (别名 `35xq`, ~22 GB) — **已删除**

⚠ 模型文件已删除。基准数据保留供参考。

APEX 量化——针对 MoE 的自适应精度策略。混合精度 per tensor（关键层 Q6_K/Q8_0，中间 expert 层 Q4_K_M）。整体 ~22 GB（按体积介于 Q4~Q5，但质量接近 Q8）。imatrix 多样化校准。**比 UD-Q8+MTP 快 48%，体积仅 59%。** 曾是辅助模型，保留 mmproj 支持视觉任务。

**历史配置：F16 KV cache。** 与 35B UD-Q8 规律一致：≤128K → UB=512（prefill +15~23%）；256K → UB=256（prefill 比 UB=512 慢 4%）。

#### F16 KV UB=512（历史基准）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 84.1 | 401.7 | 0.40s |
| p4K | 80.3 | 934.9 | 8.2s |
| p32K | 62.3 | 731.1 | 49.9s |
| p64K | 57.2 | 590.0 | 117.5s |
| p128K | 47.0 | 425.1 | 319.1s |
| p256K | 32.9 | 241.0 | 1038.2s |

> APEX I-Quality 生成速度在所有 prompt 长度下**比 UD-Q8 快约 48%**（80 vs 54 t/s）。文件大小 21.9 GB vs 37 GB。

### 35B-A3B MoE APEX I-Balanced (别名 `35xb`, ~24 GB) — **已删除**

⚠ 模型文件已删除（2026-06-12）。基准数据保留供参考。

APEX 量化——最佳质量-速度平衡。混合精度 per tensor（关键层 Q6_K/Q5_K_M，中间 expert 层 Q4_K_M）。整体 ~24 GB（按体积介于 Q5~Q6）。KL max 4.53——**所有量化中最低**（甚至优于 Q8 的 9.72）。imatrix 校准将最坏偏差降低 68%。

**最优配置：F16 KV cache。** UB 规律一致：≤128K → UB=512；256K → UB=256。

#### F16 KV UB=512（≤128K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 75.2 | 377.5 | 0.42s |
| p4K | 75.7 | 903.0 | 8.51s |
| p32K | 62.9 | 706.2 | 51.71s |
| p64K | 56.1 | 575.9 | 120.35s |
| p128K | 45.3 | 417.3 | 325.07s |
| p256K | 35.8 | 240.9 | 1038.41s |

#### F16 KV UB=256（256K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 78.2 | 435.3 | 0.37s |
| p4K | 78.9 | 731.9 | 10.50s |
| p32K | 65.1 | 577.9 | 63.19s |
| p64K | 56.7 | 475.7 | 145.70s |
| p128K | 44.5 | 356.7 | 380.26s |
| p256K | 32.0 | 246.9 | 1013.52s |

> APEX I-Balanced 生成速度**比 UD-Q8 快约 40%**。质量领先：KL max 4.53 为所有量化最优。
>
> **基准测试后配置更新（2026-06-06）：** `spec-draft-n-max` 3→2（gen 速度 +5~12%），`ubatch-size` 512→256（长上下文稳定性），`cache-reuse=256`（改善多轮对话），`max_cstate=1` + `governor=performance`（系统级延迟降低）。这些变更影响了 gen 速度和 TTFT，但以上 UB=512 基准表在这些更新之前测量——实际使用当前配置性能有所不同。

### 27B Dense Q8 (Q8_K_XL, 别名 `278`)

Dense 架构——每 token 激活全部 27B 参数。当前 Hermes 默认模型。

**配置：F16 KV + UB=256 + kv-unified=1 + cache-ram=49152 + slot-prompt-similarity=0.8。**

**已排除：** Q8_0 KV（1.7~2× KV 空间 vs Q4_0，无显著 prefill 优势）；Q4_0 KV（Vulkan 反量化开销抵消带宽节省）；UB≥1024（长上下文 prefill 退化 11–34%）；UB≥2048（Vulkan 崩溃）。

#### F16 KV UB=256（当前配置, b9692）

**Gen 速度按响应长度分布**（1001 个任务, decoded ≥ 100 tokens）：

| 响应长度 | 任务数 | 平均 (t/s) | P50 (t/s) |
|---------|-------|-----------|----------|
| <200 tokens | 237 | 11.6 | 11.7 |
| 200–500 | 395 | 11.7 | 11.8 |
| 500–1K | 178 | 10.7 | 10.5 |
| 1K–3K | 149 | 10.7 | 10.4 |
| 3K–5K | 23 | 10.7 | 10.8 |
| 5K+ | 19 | 10.0 | 10.0 |

**Gen 速度按上下文长度分布**（1183 个任务）：

| 上下文 | 任务数 | P50 (t/s) | 均值 (t/s) |
|---------|--------|-----------|------------|
| <4K | 837 | 10.9 | 11.2 |
| 4–16K | 258 | 11.8 | 11.8 |
| 16–64K | 71 | 12.7 | 12.3 |
| 64–130K | 13 | 10.0 | 10.2 |
| 130–200K | 4 | 8.5 | 8.5 |

**Prefill 速度按提示长度分布**（1033 个任务, tokens ≥ 100）：

| 提示长度 | 任务数 | 平均 (t/s) | P50 (t/s) |
|---------|-------|-----------|----------|
| <1K | 397 | 60.5 | 38.1 |
| 1K–5K | 333 | 78.9 | 40.2 |
| 5K–10K | 147 | 84.9 | 54.0 |
| 10K–30K | 126 | 122.0 | 132.6 |
| 30K–60K | 13 | 91.1 | 93.2 |
| 60K–130K | 13 | 78.8 | 63.9 |
| 130K+ | 4 | 39.9 | 39.3 |

> † 生产负载日志数据（F16 KV, UB=256, cache-ram=49152, llama.cpp b9692, 1001 gen + 1033 prefill 任务）。Gen 速度含 thinking tokens。短/中上下文 gen 稳定 11–13 t/s；长上下文（5K+ decoded）8–10 t/s。Prefill 随缓存命中率变化较大；短上下文（<5K）P50 偏低因为多为 cache 命中后的增量 prefill。真实冷启动 prefill：16K+ 达 150–226 t/s（中位数 ~200 t/s），130K+ 约 45 t/s。MTP 接受率：均值 87.1%，中位数 89.2%。
>
> **历史参考（b9625, 378 gen + 413 prefill 任务）：** Gen 按响应长度均值: <200=11.7, 200–500=12.0, 500–1K=10.8, 1K–3K=10.2, 3K–5K=10.1, 5K+=9.2。Prefill 按提示长度均值: <1K=50, 1K–5K=71, 5K–10K=79, 10K–30K=132, 30K–60K=62, 60K–130K=91, 130K+=46。Gen 速度在 b9625→b9692 间一致；prefill 模式一致，样本量更大。
>
> **历史参考（Q8_0 KV UB=512，已弃用）：** p128=127.4, p4K=247.3, p32K=194.6, p64K=160.2, p128K=119.1, p256K=82.8 t/s prefill；gen 7.3–13.8 t/s。

### 27B Dense Q6 (Q6_K_XL, 别名 `276`) — **已删除**

⚠ 模型文件已删除。基准数据保留供参考。

Dense 架构 Q6 量化——曾是速度与精度最佳平衡。

**历史配置：Q8_0 KV + UB=512。**

#### Q8_0 KV UB=512（历史基准）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 18.9 | 140.8 | 1.1s |
| p4K | 17.2 | 244.0 | 31.5s |
| p32K | 15.8 | 194.6 | 187.7s |
| p64K | 14.2 | 160.3 | 432.3s |
| p128K | 11.2 | 119.1 | 1139.1s |
| p256K | 8.8 | 82.7 | 3025.1s |

> p256K 总耗时：3130s（~52 分钟）。

### 27B Dense Q4 (Q4_K_XL, 别名 `274`) — **已删除**

⚠ 模型文件已删除。基准数据保留供参考。

Dense 架构 Q4 量化——曾是 Dense 模型中最快生成速度。

**历史配置：Q8_0 KV + UB=1024。**

#### Q8_0 KV UB=1024（历史基准）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 26.5 | 161.9 | 1.0s |
| p4K | 25.1 | 314.9 | 24.4s |
| p32K | 20.1 | 244.9 | 149.1s |
| p64K | 18.4 | 189.4 | 366.0s |
| p128K | 14.5 | 133.2 | 1018.6s |
| p256K | 10.4 | 88.9 | 2814.1s |

> p256K 总耗时：2886s（~48 分钟）。

### 跨模型对比（最优配置）

| Prompt | APEX I-Q | APEX I-B | 35B UD-Q8 | 27B Q8 | 27B Q6 | 27B Q4 |
|--------|---------|---------|--------|--------|--------|--------|
| p128 Gen | 84.1 | 78.2 | 56.7 | 13.8 | 18.9 | 26.5 |
| p4K Gen | 80.3 | 78.9 | 56.7 | 13.4 | 17.2 | 25.1 |
| p32K Gen | 62.3 | 65.1 | 50.1 | 12.5 | 15.8 | 20.1 |
| p64K Gen | 57.2 | 56.7 | 46.7 | 12.1 | 14.2 | 18.4 |
| p128K Gen | 47.0 | 45.3 | 38.0 | 10.0 | 11.2 | 14.5 |
| p256K Gen | 32.9† | 32.0† | 29.3† | 7.3 | 8.8 | 10.4 |
| p256K TTFT | 996s† | 1014s† | 999s† | 3022s | 3025s | 2814s |

> 配置：APEX I-Q/I-B = F16 KV（≤128K: UB=512, †256K: UB=256），35B Q8 = F16 KV（≤128K: UB=512, †256K: UB=256），27B Q8/Q6 = Q8_0 KV UB=512，27B Q4 = Q8_0 KV UB=1024。Gen 速度含 thinking tokens。

### 智力测试（35B MoE，MTP 已开启）

8 道题覆盖数学、逻辑、计算机科学和哲学。基于关键词匹配评分（每题满分 10，总分 80）。所有模型使用 F16 KV + UB=512 + MTP（`--spec-type draft-mtp --spec-draft-n-max 2`）。

| 题目 | 35xq (I-Q) | 35xb (I-B) | 358 (Q8) |
|------|-----------|-----------|----------|
| 高斯求和 (1+2+...+100) | 10/10 | 10/10 | 10/10 |
| 三段论有效性 | 0/10 | 4/10 | 4/10 |
| 二分查找复杂度 | 3/10 | 3/10 | 3/10 |
| 渡河问题 | 10/10 | 10/10 | 10/10 |
| 量子纠缠 | 5/10 | **8/10** | 3/10 |
| 定积分 ∫₀¹x²dx | 3/10 | 3/10 | 3/10 |
| 说谎者悖论 | 7/10 | 7/10 | **10/10** |
| LRU 缓存设计 | 10/10 | 10/10 | 10/10 |
| **总分** | **48/80** | **55/80** 🏆 | **53/80** |
| 平均 Gen 速度 | 82.3 t/s | 81.7 t/s | 57.3 t/s |

> APEX I-Balanced 智力得分最高（55/80）——imatrix 校准可能更好地保留了 MoE 模型的推理模式。I-Quality 速度最快但推理错误更多（尤其三段论 0/10）。三者均在三段论上表现不佳（关键词评分可能过严）。UD-Q8 在说谎者悖论拿到满分，APEX 模型均得 7/10。

### 视觉测试（35B MoE + mmproj，MTP 已开启）

三个 35B MoE 模型共用 `mmproj-F16.gguf`（899 MB，qwen35moe 架构通用）。图片通过 base64 编码发送，使用 OpenAI chat completions API。所有模型使用 F16 KV + UB=512 + MTP。

| 图片 | Prompt tokens | 模型 | Gen (t/s) | MTP 命中率 | 耗时 |
|------|-------------|------|-----------|-----------|------|
| 婴儿趴睡 (83 KB) | 939 | 35xq | **73.5** | 55.8% | 16.7s |
| | | 35xb | 69.6 | 52.4% | 14.6s |
| | | 358 | 51.2 | 50.9% | 18.3s |
| 户外照片 (1.4 MB) | 2059 | 35xq | **69.8** | 52.3% | 22.3s |
| | | 35xb | 65.4 | 48.4% | 23.4s |
| | | 358 | 49.3 | 48.2% | 28.4s |
| 生日照片 (2.8 MB) | 4034 | 35xq | 70.5 | 53.9% | 35.2s |
| | | 35xb | **71.1** | 56.6% | 35.2s |
| | | 358 | 53.5 | 55.2% | 39.9s |

> 视觉模式下 MTP 命中率（48–57%）明显低于纯文本模式（60–70%），因为视觉 token 更难预测。APEX I-Quality 视觉生成比 UD-Q8 快约 39%。三个模型均能准确描述图片内容。

---

## 优化参数

### 关键决策及理由

| 决策 | 理由 |
|------|------|
| Service = 服务级，INI = 模型级 | 层次清晰，改模型参数不碰 service 文件 |
| 统一 parallel=1, ctx=262144 | 简化配置；单用户负载无需并发 slot；单模型模式 `--models-max 1`；256K 上下文覆盖所有 prompt 长度 |
| 统一 UB=256 | 全模型统一 ubatch=256，保证稳定性。此前 278 UB=512 导致不稳定（后改为 256）；UB≥1024 长上下文 prefill 退化；UB≥2048 Vulkan 崩溃 |
| `cache-ram = 49152/65536`（INI 中每模型配置） | prompt cache 按模型配置：278=48 GB（主力，单模型模式长对话），358=64 GB（辅助，为后续双模型预留）。单模型模式（`models-max 1`）将全部 GTT 分配给一个模型，允许更大 cache-ram。此前双模型模式为 `16384/4096` |
| `reasoning-budget = 16384`（INI 中每模型配置） | 防止思考 token 失控增长，同时允许更长推理链。此前 8192，已加倍以改善推理质量 |
| 不使用 `reasoning-format = none` | 该参数会将 thinking 内容放入 `delta.content` 而非 `delta.reasoning_content`，导致 SSE 客户端（如 OpenClaw/QClaw）混入思考和回答，产生重复输出。不要添加 |
| 所有模型: `parallel = 1`，`ctx-size = 262144` | 每 slot 256K 上下文；单用户负载无需并发 slot；`parallel > 1` 浪费 KV cache 内存 |
| 服务：`--models-max 1` | 单模型模式：仅 278 常驻加载。358 可手动切换（8-17 秒冷加载）。此前 `models-max 2`（双模型常驻）导致 GTT 内存压力；改为单模型 + 更大 cache-ram（278=49152）。Slot-save-path 提供切换时的 KV checkpoint 持久化 |
| 27B Dense: `parallel = 1` | `parallel ≥ 3` 在 27B Dense 上触发 Vulkan bug（见已知问题） |
| `--spec-draft-n-max 2` | 3 比 2 慢 20.6%；2 在量化 KV cache 下提供最佳速度/准确率平衡 |
| 全部模型 `-t 8` | 全 GPU 卸载下 t=8 vs t=16 无实质差异，t=8 更低温 |
| 不加 `--no-mmap` | 无收益，`--mmap`（默认）+ `--mlock` 是最佳组合 |
| `-a Qwen3.6` | 设置 API 响应中的 model 字段；客户端需校验 model 字段时必须 |
| alias 短名路由 | 无需符号链接；别名和文件名均可路由 |
| 所有模型：F16 KV cache（默认） | INI 中无显式 `cache-type-k`/`cache-type-v`，llama-server 默认 F16。Q4_0 此前在 278 上测试节省约 50% 空间且 prefill 持平，但当前未使用。不要在 Vulkan 后端启用量化 KV（见已知问题：MTP + 量化 KV） |
| `kv-unified = 1`（全模型） | 统一 KV cache，Vulkan 后端 slot-save/restore 兼容性所必需；同时绕过 Vulkan 统一内存上的 GGML_ASSERT 崩溃路径 |
| 系统: CPU governor=performance | 减少 GPU 命令提交延迟；改善 gen 速度和 TTFT 稳定性 |
| 系统: `processor.max_cstate=1` | 阻止 CPU 进入深 C-state；减少 Vulkan 命令提交延迟尖峰 |
| 系统: `vm.swappiness=1`, `vm.overcommit_memory=1` | 最小化 swap 使用，防止 OOM killer 误杀 |
| 不加 `--sleep-idle-seconds` | 已加载模型常驻；空闲卸载→重载循环会导致内存尖峰和 OOM（见已知问题） |

### 使用约束

| 约束 | 值 | 原因 |
|------|---|------|
| 所有模型: 并发槽位 | 1 (`parallel = 1`) | 单用户负载；`parallel > 1` 浪费 KV cache 内存 |
| 所有模型: 最大上下文 | 256K (`ctx-size = 262144`) | 统一上下文覆盖所有 prompt 长度 |
| 27B Dense: `parallel` | 仅 1 | `parallel ≥ 3` 触发 Vulkan bug（见已知问题） |
| 35B MoE: UB 约束 | UB=256（当前，全上下文长度稳定） | 278 UB=512 导致不稳定；358 切换 UB=256 保证稳定性；UB≥1024 在 p256K 劣化；UB≥2048 Vulkan 崩溃 |
| 27B Dense: UB 约束 | UB=256（当前，与 358 统一） | UB=512 此前不稳定，已统一为 256；UB≥1024 长上下文退化；UB≥2048 Vulkan 崩溃 |
| Thinking 模式 | 所有模型：已开启（`reasoning-budget=16384`） | Budget 上限防止思考 token 失控增长；`reasoning=off` 会导致 checkpoint 恢复 bug（见已知问题）；客户端通过 `chat_template_kwargs.enable_thinking: false` 在请求层面控制 |
| 不使用 `reasoning-format = none` | 该参数会将 thinking 内容放入 `delta.content` 而非 `delta.reasoning_content`，导致 SSE 客户端（如 OpenClaw/QClaw）将 thinking 与正式回答混合，引发重复输出。不要添加。 |
| 并发 | 所有模型 parallel=1 | 单用户负载无需并发 slot；27B Dense parallel≥3 触发 Vulkan bug |
| `cache-ram` | 278=`16384`, 358=`4096`（IN I 中每模型配置） | prompt cache 按模型角色设定大小：278（主力，16 GB）覆盖 ~67K 上下文；358（辅助，4 GB）用于短任务。此前 32768（32 GB）双模型下超出 GTT 预算；`--cache-ram -1` 曾导致无限增长（见已知问题） |
| `kv-unified` | 1（全模型，在 INI 中设置） | 统一 KV cache；Vulkan slot-save/restore 所必需；绕过统一内存上的 GGML_ASSERT 崩溃 |
| b 必须被 ub 整除 | `n_batch % n_ubatch == 0` | llama.cpp 硬性要求 |

### 参数分离原则

| 范围 | 位置 | 示例 |
|------|------|------|
| **服务级** | `llm-router.service` ExecStart | `--host`, `--port`, `--api-key`, `--models-dir`, `--models-max`, `--models-preset`, `--timeout` |
| **模型级** | `router-preset.ini` 每模型 section | `n-gpu-layers`, `ctx-size`, `ubatch-size`, `threads`, `alias`, `spec-type`, `mlock`, `numa`, ... |

> 模型参数**仅**在 INI 中定义——不要在 service 文件中重复。
>
> 完整的 Preset INI 和 service 配置见下方各客户端章节（Hermes / QClaw）。

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
- **别名短名**（278/358）便捷路由

### 硬件

| 组件 | 规格 |
|------|------|
| 机型 | {your_machine} 迷你主机 |
| APU | AMD Ryzen AI Max+ 395 (16C, SMT 已关闭) |
| 内存 | 128 GB LPDDR5X (256-bit, 统一内存) |
| 存储 | 1 TB NVMe SSD |
| 核显 | Radeon 8060S (RDNA 3.5, 40 CU, 2040 MHz) |
| GTT (GPU 可访问内存) | 120 GB (内核参数 `amdgpu.gttsize=122880`) |

**内存带宽：** 256-bit × 8000 MT/s ÷ 8 = **256 GB/s** 理论值，~200 GB/s 实际值。Dense 模型受内存带宽限制。

### BIOS 配置

| 设置项 | 值 | 目的 |
|--------|-----|------|
| SMT（同步多线程） | **Disabled** | LLM 推理受内存带宽限制；关闭 SMT 减少缓存争抢，提升 KV cache 命中率 |
| GFX Workstation Support | **Disabled** | 无头推理不需要；释放资源 |
| iGPU Mem Bar Configuration | **ResizableBAR** | 允许 GPU 访问完整系统内存以加载大型模型权重 |
| UMA Version | **Non-Legacy** | ResizableBAR 和大容量统一内存分配的必要条件 |
| Dedicated Graphics Memory | **0.5G** | 最小分配；模型权重通过 GTT 由系统内存承载 |

> **为什么关闭 SMT？** 统一内存上的 LLM 推理是带宽受限的（256 GB/s）。SMT 增加了共享 L3 缓存的线程争抢，但无法提升带宽利用率。实测表明关闭 SMT 后缓存命中率更稳定，延迟更低。

### GRUB 内核参数

**文件：** `/etc/default/grub`

```bash
GRUB_CMDLINE_LINUX_DEFAULT="amd_iommu=off amdgpu.gttsize=122880 processor.max_cstate=1"
```

- `amd_iommu=off` — 禁用 IOMMU，减少 GPU DMA 的内存转换开销
- `amdgpu.gttsize=122880` — 设置 GPU 可访问的系统内存（GTT）为 120 GB，允许 iGPU 访问几乎全部 128 GB RAM 用于模型权重
- `processor.max_cstate=1` — 禁止 CPU 进入深度 C-state，降低 Vulkan GPU 命令提交和 KV cache 操作的延迟

**应用：** `sudo update-grub && sudo reboot`

### 软件

| 组件 | 版本 / 详情 |
|------|------------|
| 推理机系统 | Ubuntu 26.04 LTS |
| 云端系统 | Ubuntu 24.04.4 LTS |
| llama.cpp | b9692 (Vulkan 后端) |
| 构建选项 | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` |

> ⚠️ **版本从 b9315 升级至 b9592（2026-06-11）→ b9617（2026-06-13）→ b9625（2026-06-14）→ b9692（2026-06-18）。** 主要变更：Vulkan 连续缓冲传输快速路径（#23973）、Vulkan memcpy 管线屏障（#23770）、server checkpoint pos_next 修正（#24411）、reasoning-budget WebUI 优先级修复（#24517）、router 模式日志清理（#24463）、Vulkan non-contig unary/glu ops 修复（#24215）、Jinja 模板 bug 修复（#24574, #24580）、server UI 静态资源重构（#24550）。commit `6c4cbdc70`（"server: MTP layer kv-cache should respect draft type ctk"）仍在 b9592 中，但当前部署使用默认 F16 KV cache（INI 中无显式 `cache-type-k`/`cache-type-v`），因此此 bug **当前不会触发**。仅当重新启用量化 KV（如 `q8_0`、`q4_0`）时才会出现。不要在 Vulkan 后端启用量化 KV，直到上游修复。
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
| Router preset（全模型） | `$HOME/model/router-preset.ini` |

### 模型清单

Router Mode 从 `$HOME/model/` 提供所有模型服务。单模型模式（`--models-max 1`）：278 默认常驻加载；358 可手动切换（8-17 秒冷加载）。每个模型配置了 **alias 别名** 便于 API 路由。

**模型来源（HuggingFace）：**

| 来源 | 缩写 | 模型 | 描述 |
|------|------|------|------|
| [unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | **UD-35B** | 358 | Unsloth Dynamic 量化，35B MoE |
| [mudler/Qwen3.6-35B-A3B-APEX-MTP-GGUF](https://huggingface.co/mudler/Qwen3.6-35B-A3B-APEX-MTP-GGUF) | **APEX-35B** | 35xb, 35xq | APEX 自适应精度量化，35B MoE |
| [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) | **UD-27B** | 278, 276, 274 | Unsloth Dynamic 量化，27B Dense |

| 别名 | 文件名 | 来源 | 量化 | 架构 | 大小 | 激活参数 | 角色 |
|------|--------|------|------|------|------|----------|------|
| **35xb** | `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced.gguf` | APEX-35B | APEX 混合精度 | **MoE** | ~24 GB | 3B | 已删除（文件已删除 2026-06-12） |
| **358** | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | UD-35B | UD-Q8_K_XL | **MoE** | ~37 GB | 3B | 辅助（Hermes 辅助任务，视觉） |
| **35xq** | `Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf` | APEX-35B | APEX 混合精度 | **MoE** | ~22 GB | 3B | 已删除（文件已移除） |
| **278** | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | UD-27B | UD-Q8_K_XL | Dense | ~33 GB | 27B | 主力（Hermes 默认 + fallback） |
| **276** | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | UD-27B | UD-Q6_K_XL | Dense | ~25 GB | 27B | 已删除（文件移除） |
| **274** | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | UD-27B | UD-Q4_K_XL | Dense | ~17 GB | 27B | 已删除（文件移除） |

> **别名命名约定** 35b 保留给 Qwen3.6-35B-A3B 架构族。APEX 变体使用 35xb（I-Balanced）和 35xq（I-Quality）。UD 模型使用 3 位数字 = 模型大小 + 量化等级（如 358 = 35B Q8，276 = 27B Q6）。别名和完整文件名均可用于 API 请求。
>
> **部署模式：**
> - **单模型模式**：models-max 1 → 278 默认常驻加载；358 可手动切换（8-17 秒冷加载）。每模型 cache-ram 限制（278=49152, 358=65536）按单模型 GTT 预算配置。GTT 120GB + mlock=1。不加 --sleep-idle-seconds。
>
> **已删除模型：** 35xb (24 GB, 2026-06-12 删除), 35xq (21.9 GB), 276 (25 GB), 274 (17 GB) 已删除以回收磁盘空间。基准数据和测试脚本保留在 git 历史中。

### 1. 云端 Nginx 配置

**文件：** `/etc/nginx/sites-enabled/default`（LLM 相关部分）

#### nginx.conf 关键配置

```nginx
server_tokens off;          # 隐藏 Nginx 版本号
gzip off;                   # 全局禁用 gzip，由各 location 独立控制

# 限流（http 块内）
limit_req_zone $binary_remote_addr zone=api:10m rate=60r/m;
```

#### LLM 相关 location

```nginx
server {
    listen 443 ssl default_server;
    client_max_body_size 64m;   # 支持长 prompt 大请求
    server_tokens off;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # /v1/props — Hermes 功能探测，llama-server 未实现此端点
    location = /v1/props {
        access_log off;
        default_type application/json;
        return 200 '{}';
    }

    # LLM 推理 API（OpenAI 兼容）— SSH 隧道端口 8080 → llama-server
    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        limit_req zone=api burst=20 nodelay;

        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 长超时（Nginx ≥ llama-server --timeout 3600）
        proxy_read_timeout 3600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;

        # SSE 流式响应
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        gzip off;              # SSE 必须禁用 gzip
    }

    # 健康检查
    location /health {
        limit_req zone=api burst=20 nodelay;
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**配置说明：**
- **`/v1/`** — OpenAI 兼容 API 代理到 `127.0.0.1:8080`（SSH 反向隧道 → 推理机）
- `/v1/props` 直接返回 `{}`，避免 Hermes 功能探测 404 噪音
- `limit_req_zone 60r/m burst=20` — 所有 location 统一限流
- `server_tokens off` — 双重保险（nginx.conf + server block）
- `client_max_body_size 64m` — 支持 100K+ tokens 的长 prompt
- 全局 `gzip off`，SSE 的 `/v1/` 显式 `gzip off`（防止 location 级覆盖）
- 所有超时对齐：Nginx 3600s ↔ llama-server 3600s ↔ Hermes 3600s

**应用：** `sudo nginx -t && sudo systemctl reload nginx`

**链路延迟参考**（WSL → 云端 Nginx → SSH 隧道 → 推理机）：

| 端点 | TTFB | 说明 |
|------|------|------|
| `/v1/props` | ~165ms | Nginx 直接返回 `{}` |
| `/v1/models` | ~390-480ms | 代理到 llama-server |
| `/v1/chat/completions` (短) | ~1.3s | 含推理时间 |

> 纯链路开销（DNS + TLS + SSH 隧道）：~400-500ms。这是 SSH 反向隧道架构的固有成本。

### 2. 云端 SSH 服务端

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

### 3. SSH 反向隧道（systemd）

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
    {your_server_user}@{your_server_ip}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

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
ssh -R 8080:127.0.0.1:12345 {your_server_user}@{your_server_ip} -N
# 在云端验证：
curl http://127.0.0.1:8080/v1/models
```

**SSH 密钥设置（免密登录）：**
```bash
ssh-keygen -t ed25519 -C "llm-tunnel@{your_hostname}"
ssh-copy-id {your_server_user}@{your_server_ip}
```

### 4. Swap 配置（Ubuntu）

```bash
# 查看当前 swap
swapon --show

# 创建 32 GB swap 文件
sudo fallocate -l 32G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 开机自动挂载
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

> 32 GB swap 为双模型冷加载内存尖峰提供安全余量。在移除 `--sleep-idle-seconds` 且模型常驻的情况下，实际 swap 使用极少（实测 ~17 MB）。

### 5. GPU 温度监控

FEVM FAEX1 迷你主机主板的 ITE 0x5571 芯片无上游 Linux `lm-sensors` 驱动，AMD Ryzen AI Max+ 395 的 `k10temp` 模块在内核 7.0.0-15 上也未被识别。但 GPU 温度可通过 `amdgpu` hwmon 子系统读取。

**监控脚本：** `~/scripts/gpu-temp-log.sh`

```bash
#!/bin/bash
# GPU 温度记录脚本 — 读取 amdgpu hwmon
# 通过 systemd user timer 每 5 分钟执行一次

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

echo "$ts | GPU ${gpu_temp_c}°C (结温 ${junc_str}, 显存 ${mem_str}) | ${gpu_busy}% 占用 | ${gpu_pwr_w}W | 内存 ${mem_used_gb}/${mem_total_gb}GB"
```

**systemd 用户定时器：** `~/.config/systemd/user/gpu-temp-log.timer`

```ini
[Unit]
Description=GPU 温度记录定时器

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

**systemd 用户服务：** `~/.config/systemd/user/gpu-temp-log.service`

```ini
[Unit]
Description=GPU 温度记录

[Service]
Type=oneshot
ExecStart=/bin/bash -c '/home/$USER/scripts/gpu-temp-log.sh >> /home/$USER/logs/gpu-temp.log 2>&1'
```

**部署步骤：**

```bash
mkdir -p ~/scripts ~/logs
# 将脚本保存到 ~/scripts/gpu-temp-log.sh
chmod +x ~/scripts/gpu-temp-log.sh
# 将 service 和 timer 单元保存到 ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gpu-temp-log.timer
```

**日志格式：** `时间戳 | GPU 温度 (结温, 显存温度) | GPU 占用率 | 功耗 | 内存已用/总量`

**示例输出：**
```
2026-06-03 13:25:28 | GPU 82°C (结温 N/A, 显存 N/A) | 100% 占用 | 108W | 内存 106.0/124.9GB
```

> **注意：** 此 APU 无法获取结温和显存温度（amdgpu 驱动未暴露 temp2_input/temp3_input）。GPU 边缘温度（`temp1_input`）是主要监控指标。满载推理下观测范围：78–82°C（TjMax 100°C）。

### 6. Preset INI（模型级参数）

**文件：** `~/model/router-preset.ini`

```ini

[Qwen3.6-27B-UD-Q8_K_XL]                    # alias: 278 — 主力（Hermes 默认 + fallback）
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

[Qwen3.6-35B-A3B-UD-Q8_K_XL]                # alias: 358 — 辅助（手动切换，视觉能力）
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

**修改模型参数：** 编辑 INI 文件 → 重启 llama-server（`systemctl --user restart llm-router` 或手动重启）

### 7. 推理服务（systemd）

**文件：** `~/.config/systemd/user/llm-router.service`（用户级，无需 sudo）

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
loginctl enable-linger   # 注销后保持运行
```

> 服务使用 wrapper 脚本（`llama-router.sh`）处理 SIGTERM 清理（退出前保存 KV checkpoint）和日志输出。`ExecStartPost` 在启动时自动恢复上次 checkpoint。wrapper 内部以 `--models-max 1`（单模型模式，278 常驻）和 `--models-preset`（从 INI 读取每模型参数）启动 llama-server。模型参数（cache-ram, ubatch 等）仅在 INI 中定义，不重复在 service 文件中。GTT 120GB + mlock=1 确保模型权重常驻物理内存。`LimitMEMLOCK=infinity` 允许 mlock 锁定全部模型权重。`TimeoutStartSec=300` 防止 systemd 在长时间模型加载时杀死服务。

### 8. 模型切换

客户端在请求中指定 `model` 字段即可自动切换（LRU，冷切换耗时 8–17 秒）。**别名和完整文件名均可**：

```bash
# 使用别名（推荐）
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "278", ...}'   # 主力模型（Hermes 默认）

# 使用完整文件名（也可以）
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "Qwen3.6-35B-A3B-UD-Q8_K_XL", ...}'

# 切换到辅助模型（视觉、压缩等）
curl https://{your_domain}/v1/chat/completions \
  -H "Authorization: Bearer {your_api_key}" \
  -d '{"model": "358", ...}'
```

### 客户端集成

#### Hermes Agent

[Hermes](https://github.com/nicobailon/hermes-agent) v0.16.0 — 终端 AI Agent，支持 TUI、oneshot 模式、多平台 Gateway（Telegram/Discord/钉钉/飞书/企微/QQ/微信等）、MCP、Skills 和 cron 调度。

**安装路径：** WSL Ubuntu 26.04 上的 `~/.hermes/`

**配置文件：** `~/.hermes/config.yaml` — 两套独立部署，各用一个模型：

| | 机器 A（278-only） | 机器 B（358-only） |
|---|---|---|
| **model.default** | `278`（27B Dense） | `358`（35B MoE） |
| **providers.models** | 仅 `278` | 仅 `358` |
| **supports_vision** | `false` | `true`（mmproj） |
| **auxiliary 任务** | 全部 → `278`，禁用视觉 | 全部 → `358`，启用视觉 |
| **fallback_model** | `{provider: local-llm, model: '278'}` | `{provider: local-llm, model: '358'}` |

**共享配置：**
- Provider：`local-llm` → `https://{your_domain}/v1`（v0.16.0 键名格式，不含 `custom:` 前缀）
- `key_env: DASHENZHIYAN_API_KEY`（在 `~/.hermes/.env` 中设置）
- `context_length: 262144`、`max_output_tokens: 32768`、`max_tokens: 32768`
- `request_timeout_seconds: 7200`、`stale_timeout_seconds: 7200`（与全链路超时对齐）
- `agent.gateway_timeout: 7200`、`approvals.timeout: 7200`、`approvals.gateway_timeout: 7200`
- `chat_template_kwargs.enable_thinking: true`（主模型）、`false`（auxiliary）
- `compression: threshold=0.80, target_ratio=0.30, protect_last_n=20`
- `streaming.enabled: true`（Gateway bot 流式输出）
- `approvals.mode: auto`（常规操作自动通过；破坏性操作需确认）

**环境变量覆盖**（`~/.hermes/.env`）：
```bash
HERMES_STREAM_READ_TIMEOUT=7200   # 覆盖硬编码 120s 默认值
HERMES_STREAM_STALE_TIMEOUT=7200  # 覆盖硬编码 180s 默认值
```

**⚠️ 常见陷阱：**
- `providers` 键名必须为 `local-llm`（v0.16.0），不是 `custom:local-llm`（v0.15.1）。不匹配 → 超时回退到 120s
- `auxiliary.vision.base_url` 必须显式设置（空字符串 → RuntimeError）
- `fallback_model` 必须为 dict `{provider: ..., model: ...}`，不能是裸字符串
- `yaml.dump` 可能丢失裸字符串值（如 `fallback_model: '278'` → 空）；重写后务必验证

**用法：**
```bash
wsl                                    # 进入 WSL
hermes                                 # TUI 模式（交互式）
hermes -z '快速提问'                   # oneshot 模式
```

**TUI 常用命令：** `/skills` 查看技能、`/help` 全部命令、`Ctrl+C` 中断回复、`Ctrl+D` 或 `/exit` 退出。

完整配置备份：`docs/hermes/config-278.yaml` 和 `docs/hermes/config-358.yaml`


#### TTS 语音合成服务

Qwen3-TTS 1.7B 模型运行在推理机纯 CPU 上，为监控播报系统和语音助手提供语音输出能力。

**部署信息：**

| 项目 | 详情 |
|------|------|
| 模型 | Qwen3-TTS-12Hz-1.7B-Base |
| 路径 | `/home/zxw/model/tts-1.7b-base/` |
| 服务 | systemd 用户服务 `qwen-tts.service`（port 9900, enabled） |
| 启动脚本 | `/home/zxw/scripts/qwen-tts.sh` |
| 性能 | RTF ~1.8-2.5（纯 CPU 8 线程），短文本生成 ~2.9s |
| 内存占用 | ~3.2 GB |

**API 端点：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/tts` | POST | 非流式合成，返回完整 WAV |
| `/v1/tts/stream` | POST | 流式合成，边生成边返回 |
| `/v1/audio/speech` | POST | OpenAI 兼容接口 |

**请求示例：**

```bash
curl -s -X POST http://127.0.0.1:9900/v1/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"监控已启动","speaker":3061,"volume":0.3}' \
  -o /tmp/tts_out.wav
```

**音频播放：**

推理机内置扬声器（card1 ALC245 Analog），通过 ALSA 播放：

```bash
# 播放（不阻塞当前 session）
systemd-run --user --no-block aplay -q -D plughw:1,0 /tmp/tts_out.wav
```

**ALSA 配置：** `/etc/asound.conf` 设置 `defaults.pcm.card=1`，`defaults.ctl.card=1`。

> ⚠️ SSH 远程播放音频时，不要使用 `< /dev/null` 重定向（会卡住 SSH session）。使用 `systemd-run --user --no-block` 完全脱离 SSH session。

#### 监控播报系统

运行在推理机上的自动化监控播报服务，实时监控 LLM 推理服务状态和硬件健康，通过 TTS 语音播报告警和状态。

**部署信息：**

| 项目 | 详情 |
|------|------|
| 脚本 | `/home/zxw/scripts/monitor-broadcast.py` |
| 服务 | systemd 用户服务 `monitor-broadcast.service`（enabled, Restart=on-failure） |
| 状态文件 | `~/.config/monitor-broadcast/state.json` |

**双频率轮询架构：**

| 轮询类型 | 间隔 | 监控内容 |
|---------|------|---------|
| 快速轮询 | 30s | 模型切换、推理任务全生命周期（启动/prefill完成/生成里程碑/结束/空闲） |
| 慢速轮询 | 60s | 硬件告警（GPU温度/内存/功耗）、日志 E/F 级别、日常播报（1h 间隔） |

**数据源：**

- `router.log` — LLM 推理日志（告警 + 任务状态）
- `gpu-temp.log` — GPU 温度/功耗/利用率/内存（cron 5min 写入）
- `/proc/meminfo` — 系统内存

**告警阈值：**

| 指标 | 警告 | 严重 |
|------|------|------|
| GPU 温度 | 80°C | 90°C |
| 内存使用率 | 80% | 90% |
| GPU 功耗 | 100W | 120W |

**TTS 播报队列：**

- 独立线程发送，避免播报中丢失消息
- 优先级插队：severity ≥ 3 的严重告警直接插入队列头部
- `_speak` 方法：urllib 下载 WAV → tempfile 临时文件 → `systemd-run --user --no-block aplay` 播放 → 15s 后清理

**日志告警关键字：** OOM、Xid、段错误、Vulkan 崩溃（`vk::DeviceLostError`）、子进程崩溃、Fatal、Error（E 级别），具有 5 分钟去重机制。

#### QClaw

QClaw（OpenClaw）— 个人 AI 助手，支持多渠道（微信、QQ、webchat）。

**Provider 配置**（`~/.qclaw/openclaw.json`）：
- `qclaw` provider → `http://127.0.0.1:19000/proxy/llm`（云端代理路由）
- 单模型 `modelroute`：`contextWindow: 200000`、`maxTokens: 8192`、reasoning 已开启
- 默认模型：`qclaw/pool-glm-5.1`（云端代理，不直连推理机）
- 渠道：`wechat-access`（QQ）、`openclaw-weixin`（微信本地）

**流式输出：** 微信/QQ/企微: blockStreaming；Telegram/Discord/Slack: 编辑消息式流式

### 验证清单

- [ ] 云端 Nginx 配置已更新（含 `/v1/` 和 `/health` 端点）
- [ ] 云端 SSL 证书已配置
- [ ] 云端 `sshd_config` 允许 TCP 转发和 keepalive
- [ ] 推理机已配置免密登录云端
- [ ] `llm-tunnel.service` 已创建并 **运行中**
- [ ] 云端 `ss -tlnp | grep 8080` 确认隧道监听
- [ ] `llm-router.service` 已创建并 **运行中**（仅服务级参数）
- [ ] `~/model/router-preset.ini` 配置正确（活跃模型参数 + alias：278/358）
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回模型 + aliases
- [ ] 单模型模式：278 常驻加载；358 可手动切换（8-17 秒冷加载）
- [ ] 服务配置不含 `--sleep-idle-seconds`（防止重载循环导致 OOM）
- [ ] 外网：`curl https://{your_domain}/health` 返回 `OK`
- [ ] GPU 温度监控：`systemctl --user status gpu-temp-log.timer` 处于 active 状态
- [ ] GPU 温度日志：`cat ~/logs/gpu-temp.log` 每 5 分钟有记录
- [ ] 别名路由：`curl -d '{"model":"358",...}'`、`curl -d '{"model":"278",...}'` 均可正常响应

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

**状态：** 已修复——已从 `router-preset.ini` 中移除

**受影响客户端：** OpenClaw/QClaw 及任何使用 `@mariozechner/pi-ai` OpenAI completions 解析器的 SSE 客户端。

**现象：** 助手回复包含重复内容——思考过程和正式回答混在一起，并在下一轮对话中再次出现。

**根因：** `reasoning-format=none` 让 llama-server 将思考内容放入 `delta.content`（而非标准的 `delta.reasoning_content` 字段）。OpenAI completions SSE 解析器将所有 `delta.content` 视为普通文本，创建一个同时包含思考和正式回答的单一文本块。存入对话历史后，下一轮会看到思考内容，导致模型重复输出。

**验证：** 去掉 `reasoning-format=none` 后，SSE chunk 正确分离：
- 思考 → `delta.reasoning_content` → 解析器创建独立的 `thinking` 块
- 回答 → `delta.content` → 解析器创建 `text` 块

**修复：** 从 `router-preset.ini` 所有模型 section 中删除 `reasoning-format = none`。思考内容将使用标准的 `reasoning_content` 字段。

---

### Vulkan + parallel=3 + MTP 在 27B Dense 模型上崩溃

**状态：** 未解决——等待上游修复（PR [#22453](https://github.com/ggml-org/llama.cpp/pull/22453)）

**受影响模型：** 27B Dense 系列（别名 `278`/`276`/`274`）。35B MoE 模型（别名 `358`/`35xq`）**不受**影响。276 和 274 已删除。

**现象：** 27B Dense 模型在 `parallel ≥ 3` 且启用 MTP 时，处理任何请求都会触发 `GGML_ASSERT` 导致 `llama-server` abort。

**复现：**
```ini
# router-preset.ini — 触发崩溃
[Qwen3.6-27B-UD-Q8_K_XL]
parallel = 3
spec-type = draft-mtp
spec-draft-n-max = 3
ctx-size = 786432
# ... 其他参数
```

**崩溃输出：**
```
/home/$USER/llama/llama.cpp/ggml/src/ggml-backend.cpp:348: GGML_ASSERT(tensor->data != NULL && "tensor not allocated") failed
```

**根因：** Vulkan 后端使用 device-only（统一内存）缓冲区。每个 slot 的 KV cache tensor 在 host 端 `tensor->data == NULL`（数据在 GPU 上）。`ggml_backend_tensor_get()` 及相关函数无条件断言 `tensor->data != NULL`，当 prompt cache 系统尝试保存/恢复 slot 状态（包括 MTP draft context）时触发崩溃。崩溃发生在两条路径：

1. **直接路径：** `ggml_backend_tensor_get()` — `ggml-backend.cpp:348`
2. **MTP draft 路径：** `common_prompt_checkpoint::update_dft()` → `llama_context::state_seq_get_data()` → `llama_io_write_host` — `common.cpp:2082`

**受影响代码**（`ggml/src/ggml-backend.cpp`，共 11 处）：
```cpp
// 第 348 行 — 11 处相同断言之一，在 Vulkan 统一内存上失败
GGML_ASSERT(tensor->data != NULL && "tensor not allocated");
```

**尝试的 workaround：** `--kv-unified` 可绕过崩溃路径 #1，但**无法绕过**崩溃路径 #2（MTP draft checkpoint）。不可行。

**当前缓解措施：** 所有 27B Dense 模型统一设为 `parallel = 1`（单用户场景无需并发）。牺牲并发以避免崩溃。

**上游追踪：**
- Issue [#19839](https://github.com/ggml-org/llama.cpp/issues/19839) — 原始 bug 报告
- PR [#22453](https://github.com/ggml-org/llama.cpp/pull/22453) — 提议修复（在 assert 前增加 NULL 检查，委托给 backend `get_tensor`）；已关闭但未合入
- 截至版本 b9315（commit `314e72934`），`ggml-backend.cpp` 中全部 11 处断言均未修改

---

### 双模型 + `--sleep-idle-seconds` 导致 OOM Kill

**状态：** 已解决——移除 `--sleep-idle-seconds`；当前使用单模型模式（`models-max 1`）

**历史场景：** 双模型常驻模式（`models-max 2`）+ `--sleep-idle-seconds`。空闲卸载/重载循环导致内存尖峰 OOM。已通过切换单模型模式解决。

### `reasoning=off` 导致 checkpoint 恢复灾难性变慢

**状态：** 已修复——从模型 preset 中移除 `reasoning = off` 和 `reasoning-budget = 0`，替换为 `reasoning-budget = 8192`

**受影响模型：** 仅 35B-A3B APEX I-Quality（别名 `35xq`，**已删除**）。其他模型（358/278）不受影响。

**根因：** `reasoning = off` 导致 checkpoint 保存时的 attention mask 与运行时配置不匹配，恢复时回退到慢路径重新 prefill。

**警告：** 不要重新添加 `reasoning = off`。安全做法是在服务端始终开启 reasoning，在请求层面通过 `chat_template_kwargs: { enable_thinking: false }` 控制。

---

### MTP + 量化 KV cache 触发 Vulkan DeviceLost（b9318+）

**状态：** 部分解决——已升级至 b9692（F16 KV 安全），量化 KV + Vulkan + MTP 仍不可用；等待上游修复

**受影响模型：** 所有启用 MTP speculative decoding + 量化 KV cache（`cache-type-k` / `cache-type-v`）的模型。当前部署使用默认 F16 KV（INI 中无显式 `cache-type-k`/`cache-type-v`），因此此问题**当前未触发**。仅当在任何模型上重新启用量化 KV（如 `q8_0`、`q4_0`）时才会出现。当前活跃模型（278/358）一直使用 F16 KV，不受影响。

**现象：** MTP draft decode 期间触发 `vk::DeviceLostError`（`vk::Queue::submit: ErrorDeviceLost`），llama-server slot 进程崩溃。客户端看到 HTTP 500 / "Failed to read connection"。

**复现：**
```ini
# router-preset.ini — 在 b9318+ 上触发崩溃
[Qwen3.6-27B-UD-Q4_K_XL]
parallel = 1
ctx-size = 262144
cache-type-k = q8_0       # 量化 KV
spec-type = draft-mtp      # 启用 MTP
spec-draft-n-max = 3
# ...
```

**罪魁祸首 commit：** `6c4cbdc70` —— "server: MTP layer kv-cache should respect draft type ctk" (#23646)。在 `tools/server/server-context.cpp` 中新增 4 行，为 MTP context 设置 `type_k` 和 `type_v`。当 MTP context 使用量化 KV 格式（如 `q8_0`）时，Vulkan 后端在长上下文场景触发 `vk::DeviceLostError`。

**二分定位：** b9297 GOOD → b9315 GOOD → b9318 BAD。6 轮二分。

**压测结果（b9465，278 模型）：**

| 配置 | p32K | p64K | p128K | p256K |
|------|------|------|-------|-------|
| MTP + Q8_0 KV | ✅ | ❌ DeviceLost | ❌ DeviceLost | — |
| 无 MTP | — | ✅ | ✅ | ✅ |
| b9315 + MTP | ✅ | ✅ | ✅ | ✅（128K tokens 验证通过） |

**根因：** MTP draft KV cache 使用量化类型触发了 radv/amdgpu Vulkan 驱动 bug。长上下文场景（≥64K tokens）高频 GPU 提交导致 device context 丢失。bug 位于量化 MTP KV cache 与 Vulkan 内存管理的交互——不在 commit 本身的逻辑，但该 commit 暴露了潜在问题。

**Workaround：** 已升级至 b9692（当前使用 F16 KV 不触发此 bug）。在上游修复 Vulkan + 量化 KV cache 交互前**不要**启用量化 KV 类型。

**上游追踪：** 尚未提交 issue。此回归仅影响 Vulkan 后端 + MTP + 量化 KV；其他后端（CPU/CUDA/Metal）不受影响。

---

### `--cache-ram -1` 导致 VRAM 争抢和 35B 冷加载卡死

**状态：** 已缓解——prompt cache 现在在 INI 中每模型配置（278 `cache-ram = 49152`，358 `cache-ram = 65536`）。单模型模式（`models-max 1`）防止无限增长。

**现象：** `--cache-ram -1` 允许 prompt cache 无限增长。单模型模式下 278 缓存占用 ~12+ GB，剩余空间不足导致 358 冷加载卡死 20+ 分钟。

**修复：** 每模型 `cache-ram` 限制 + 单模型模式。**切勿**使用 `--cache-ram -1`（任何模式）。

---

### Hermes Vision `base_url: ''` 导致 RuntimeError

**状态：** 已修复——将 `auxiliary.vision.base_url` 设为 `https://{your_domain}/v1`

**受影响场景：** Hermes 配置中 `auxiliary.vision.base_url` 为空字符串（`''`）。

**现象：** 视觉请求失败，报 `RuntimeError: No LLM provider configured for task=vision`。

**根因链：**
1. `resolve_vision_provider_client()` 先检查 `base_url`——空字符串为 falsy → 跳过显式分支
2. `requested="custom:local-llm"` ≠ `"auto"` → 跳过自动检测分支
3. 走兜底 `_get_cached_client(is_vision=True)` → `resolve_provider_client()` 无法解析 `custom:*` + `is_vision=True` → 返回 None
4. `None` → RuntimeError

**关键洞察：** 非视觉辅助任务（web_extract、compression 等）空字符串 `base_url` 正常工作，因为其代码路径走 `_get_cached_client(is_vision=False)`，能正确解析命名 provider。只有视觉路径有此额外 `base_url` 分支。

**修复：** 显式设置 `auxiliary.vision.base_url` 为 `https://{your_domain}/v1`。即使 provider 已定义 `base_url`，视觉解析路径也不会回退到 provider 的 `base_url`。

**警告：** 修改 Hermes 配置后（包括 `yaml.dump` 重写），必须确认 `auxiliary.vision.base_url` 不为空。

---

### Hermes Providers 键名不匹配导致 120s 超时回退

**状态：** 已修复——v0.16.0 将 providers 键改为 `local-llm`（无 `custom:` 前缀）。v0.15.1 需要 `custom:local-llm`。

**受影响场景：** Hermes v0.15.1 配置中 `model.provider = "custom:local-llm"` 但 `providers` 字典键为 `local-llm`（缺少 `custom:` 前缀）。**v0.16.0 不受影响**——providers 键为 `local-llm`，无需前缀。

**现象：** 长上下文请求（>120K tokens）始终在 ~120s 失败，即使 `request_timeout_seconds` 已设为 3600。短请求正常，导致问题难以定位。

**根因链：**
1. Hermes 调用 `get_provider_request_timeout("custom:local-llm", "278")` 查找超时
2. 函数按完整键名（含 `custom:` 前缀）搜索 `providers` 字典
3. 若键名为 `local-llm` 而非 `custom:local-llm`，查找返回 `None`
4. `None` → 回退到硬编码 `HERMES_STREAM_READ_TIMEOUT = 120s`
5. 同理 `get_provider_stale_timeout()` 返回 `None` → 回退到 `HERMES_STREAM_STALE_TIMEOUT = 180s`
6. 278 模型 131K prefill 耗时 ~1103s → 在 120s 被杀死

**修复：** 将 `providers` 字典键从 `local-llm` 改为 `custom:local-llm` 以匹配 `model.provider`。验证方法：
```python
get_provider_request_timeout("custom:local-llm", "278")  # 应返回 3600.0，而非 None
get_provider_stale_timeout("custom:local-llm", "278")     # 应返回 3600.0，而非 None
```

**警告：** `providers` 键**必须与** `model.provider` **完全一致**，包括 `custom:` 前缀。Hermes 文档未提及此约束，容易忽略。

---

*测试环境：{your_machine} · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9692 Vulkan · 2026-06-03 · 更新于 2026-06-20（b9692 性能数据，cache-ram 49152/65536，Hermes v0.15.2，超时 7200s，TTS + 监控播报已上线）*
