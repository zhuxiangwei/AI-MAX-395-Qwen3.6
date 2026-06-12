# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 对外提供推理 API。

---

## 性能基准

所有基准测试均在 {your_machine} (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9592 Vulkan) 上完成。速度通过 API `timings` 测量（服务端，排除网络延迟）。Gen 速度含 thinking tokens。

**基准测试环境：** CPU governor=performance，`processor.max_cstate=1`，`vm.swappiness=1`，`vm.overcommit_memory=1`，GTT 120GB，mlock=1。这些系统级优化相比默认 powersave governor 改善了 gen 速度和 prefill 稳定性。

### 35B-A3B MoE (UD-Q8_K_XL, 别名 `358`)

**辅助模型——Hermes 辅助任务（视觉、压缩等）。** MoE 每 token 仅激活 35B 中的 3B 参数。~50 t/s 生成速度，支持视觉。

**最优配置：F16 KV cache。** ≤128K → UB=512（prefill +22~25%，TTFT -17~20% vs UB=256）。256K → UB=256（总耗时 -13% vs UB=512）。

**已排除：** UB=128（MTP 86%→65%，gen 更慢）；UB≥1024（p256K prefill -44%，TTFT +80%）；Q8_0 KV（反量化开销 > 稀疏 KV 带宽节省；所有 Q8_0 UB 均不如 F16 UB=256）；UB≥2048（Vulkan 崩溃 128K+）。

#### F16 KV UB=512（≤128K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 56.7 | 371.0 | 0.43s |
| p4K | 56.7 | 931.4 | 8.2s |
| p32K | 50.1 | 730.1 | 50.0s |
| p64K | 46.7 | 590.7 | 117.3s |
| p128K | 38.0 | 416.2 | 325.9s |
| p256K | 28.4 | 217.6 | 1149.7s |

#### F16 KV UB=256（256K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 58.2 | 427.9 | 0.37s |
| p4K | 54.6 | 746.9 | 10.3s |
| p32K | 48.7 | 590.0 | 61.9s |
| p64K | 46.9 | 485.1 | 142.9s |
| p128K | 38.0 | 363.1 | 373.6s |
| p256K | 29.3 | 250.4 | 999.2s |

> Gen 速度在 UB=256/512 间几乎相同（±2 t/s）。UB 选择主要影响 prefill/TTFT：UB=512 在 ≤128K 更快；UB=256 在 256K 更快。

### 35B-A3B MoE APEX I-Quality (别名 `35xq`, ~22 GB)

APEX 量化——针对 MoE 的自适应精度策略。混合精度 per tensor（关键层 Q6_K/Q8_0，中间 expert 层 Q4_K_M）。整体 ~22 GB（按体积介于 Q4~Q5，但质量接近 Q8）。imatrix 多样化校准。**比 UD-Q8+MTP 快 48%，体积仅 59%。** 辅助模型，保留 mmproj 支持视觉任务。Reasoning 默认开启（`reasoning-budget = 8192`）；客户端可通过 `chat_template_kwargs.enable_thinking: false` 在请求层面关闭 thinking。

**最优配置：F16 KV cache。** 与 35B UD-Q8 规律一致：≤128K → UB=512（prefill +15~23%）；256K → UB=256（prefill 比 UB=512 慢 4%）。

#### F16 KV UB=512（≤128K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 84.1 | 401.7 | 0.40s |
| p4K | 80.3 | 934.9 | 8.2s |
| p32K | 62.3 | 731.1 | 49.9s |
| p64K | 57.2 | 590.0 | 117.5s |
| p128K | 47.0 | 425.1 | 319.1s |
| p256K | 32.9 | 241.0 | 1038.2s |

#### F16 KV UB=256（256K 最优）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 82.4 | 396.7 | 0.40s |
| p4K | 73.5 | 761.2 | 10.1s |
| p32K | 66.8 | 597.7 | 61.1s |
| p64K | 58.8 | 488.7 | 141.8s |
| p128K | 42.9 | 364.1 | 372.5s |
| p256K | 32.2 | 251.1 | 996.4s |

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

Dense 架构——每 token 激活全部 27B 参数。~13 t/s 生成速度。当前 Hermes 默认模型（质量最高）。

**配置：F16 KV + UB=512 + kv-unified=1。**（默认 KV 类型，INI 中无显式 `cache-type-k`/`cache-type-v`）

**已排除：** Q8_0 KV（1.7~2× KV 空间 vs Q4_0，无显著 prefill 优势）；Q4_0 KV（节省约 50% 空间且 prefill 持平，但当前未使用）；UB≥1024（长上下文退化）；UB≥2048（Vulkan 崩溃）。

#### F16 KV UB=512（当前配置）

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | — | — | — |
| p4K | — | — | — |
| p32K | ~13† | 181.2† | ~189s† |
| p64K | — | — | — |
| p128K | — | 80.2† | — |
| p256K | — | 88.0† | ~2806s† |

> † 当前配置下的初步测量（F16 KV, UB=256, kv-unified=1, cache-ram=16384, reasoning-budget=16384, slot-prompt-similarity=0.8, max_cstate=1, governor=performance）。完整基准待补。
>
> **历史参考（Q8_0 KV UB=512，已弃用）：** p128=127.4, p4K=247.3, p32K=194.6, p64K=160.2, p128K=119.1, p256K=82.8 t/s prefill；gen 7.3–13.8 t/s。

### 27B Dense Q6 (Q6_K_XL, 别名 `276`)

Dense 架构 Q6 量化——速度与精度最佳平衡。

**最优配置：Q8_0 KV + UB=512。**

**已排除：** F16 KV UB≥512（p64K+ OOM/超时）；F16 KV UB=128（可跑 p256K 但总耗时 2× 慢于 Q8_0 KV：5671s vs 3130s）；Q8_0 UB=1024（p64K+ 略差）；UB≥2048（Vulkan 崩溃）。

#### Q8_0 KV UB=512

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 18.9 | 140.8 | 1.1s |
| p4K | 17.2 | 244.0 | 31.5s |
| p32K | 15.8 | 194.6 | 187.7s |
| p64K | 14.2 | 160.3 | 432.3s |
| p128K | 11.2 | 119.1 | 1139.1s |
| p256K | 8.8 | 82.7 | 3025.1s |

> p256K 总耗时：3130s（~52 分钟）。

### 27B Dense Q4 (Q4_K_XL, 别名 `274`)

Dense 架构 Q4 量化——Dense 模型中最快生成速度。

**最优配置：Q8_0 KV + UB=1024。**

**已排除：** F16 KV UB≥1024（p32K+ OOM）；F16 KV UB=128（可跑 p256K 但总耗时 1.8× 慢于 Q8_0 KV：5325s vs 2886s）；Q8_0 UB≤256（p32K+ 更慢）；UB≥2048（p256K Vulkan 崩溃）。

#### Q8_0 KV UB=1024

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
| 统一 parallel=1, ctx=262144 | 简化配置；单用户负载无需并发 slot；双模型通过 `--models-max 2` 实现；256K 上下文覆盖所有 prompt 长度 |
| 按量化等级差异化 ub | 量化越高权重越大，VRAM 余量越小，需更小 ub 保证稳定性；最优 UB 因模型而异（256–1024）。当前部署：278 使用 UB=512，358 使用 UB=256（278 UB=512 导致不稳定；358 切换到 UB=256 保证全上下文长度稳定性） |
| `cache-ram = 16384/4096`（INI 中每模型配置） | prompt cache 按模型角色配置：278=16 GB（主力，长对话），358=4 GB（辅助，短任务）。此前使用 `--cache-ram 0`（禁用），后改为 32768（32 GB，双模型下超出 GTT 预算）。67K 上下文约占 15.7 GB，16 GB 可覆盖典型长对话场景 |
| `reasoning-budget = 16384`（INI 中每模型配置） | 防止思考 token 失控增长，同时允许更长推理链。此前 8192，已加倍以改善推理质量 |
| 不使用 `reasoning-format = none` | 该参数会将 thinking 内容放入 `delta.content` 而非 `delta.reasoning_content`，导致 SSE 客户端（如 OpenClaw/QClaw）混入思考和回答，产生重复输出。不要添加 |
| 所有模型: `parallel = 1`，`ctx-size = 262144` | 每 slot 256K 上下文；单用户负载无需并发 slot；`parallel > 1` 浪费 KV cache 内存 |
| 服务：`--models-max 2` | 双模型常驻：278 和 358 可同时加载（router 模式独立 slot）。此前 `models-max 1`（单模型轮换）使用 slot-save-path 保存 checkpoint；现改为双模型 + 每模型 cache-ram 限制。早期双模型的 slot 争用问题由旧版非 router 架构导致，router 模式下每个模型独立 slot 不互锁 |
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
| 27B Dense: UB 约束 | F16 KV UB=512（当前，278） | Q8_0 KV 此前测试过；UB≥2048 Vulkan 崩溃 |
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
| llama.cpp | b9592 (commit ac4cddeb0, Vulkan 后端) |
| 构建选项 | `-DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release` |

> ⚠️ **版本从 b9315 升级至 b9592（2026-06-11）。** commit `6c4cbdc70`（"server: MTP layer kv-cache should respect draft type ctk"）仍在 b9592 中，但当前部署使用默认 F16 KV cache（INI 中无显式 `cache-type-k`/`cache-type-v`），因此此 bug **当前不会触发**。仅当重新启用量化 KV（如 `q8_0`、`q4_0`）时才会出现。不要在 Vulkan 后端启用量化 KV，直到上游修复。
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

Router Mode 从 `$HOME/model/` 提供所有模型服务。双模型常驻模式（`--models-max 2`）：278 和 358 可同时加载，router 模式下每个模型独立 slot 不互锁。每个模型配置了 **alias 别名** 便于 API 路由。

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
> - **双模型常驻**：models-max 2 → 278 和 358 可同时加载（router 模式独立 slot）。此前 `models-max 1`（单模型轮换）使用 slot-save-path 保存 checkpoint，现改为双模型 + 每模型 cache-ram 限制（278=16384, 358=4096）。早期双模型的 slot 争用问题由旧版非 router 架构导致，router 模式下每个模型独立 slot 不互锁。GTT 120GB + mlock=1。不加 --sleep-idle-seconds。
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
cache-ram = 16384
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

[Qwen3.6-35B-A3B-UD-Q8_K_XL]                # alias: 358 — 辅助（Hermes 辅助任务，视觉）
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
cache-ram = 4096
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

> 服务使用 wrapper 脚本（`llama-router.sh`）处理 SIGTERM 清理（退出前保存 KV checkpoint）和日志输出。`ExecStartPost` 在启动时自动恢复上次 checkpoint。wrapper 内部以 `--models-max 2`（双模型可同时加载）和 `--models-preset`（从 INI 读取每模型参数）启动 llama-server。模型参数（cache-ram, ubatch 等）仅在 INI 中定义，不重复在 service 文件中。GTT 120GB + mlock=1 确保模型权重常驻物理内存。`LimitMEMLOCK=infinity` 允许 mlock 锁定全部模型权重。`TimeoutStartSec=300` 防止 systemd 在长时间模型加载时杀死服务。

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

[Hermes](https://github.com/nicobailon/hermes-agent) v0.15.1 — 终端 AI Agent，支持 TUI、oneshot 模式、多平台 Gateway（Telegram/Discord/钉钉/飞书/企微/QQ/微信等）、MCP、Skills 和 cron 调度。

**安装路径：** WSL Ubuntu 26.04 上的 `~/.hermes/`

**配置文件：** `~/.hermes/config.yaml`

```yaml
providers:
  custom:local-llm:                                    # ⚠️ 必须包含 "custom:" 前缀，与 model.provider 匹配
    name: "Local LLM (Strix Halo)"
    base_url: "https://{your_domain}/v1"
    key_env: "DASHENZHIYAN_API_KEY"
    extra_body:
      chat_template_kwargs:
        enable_thinking: true       # 启用思考模式
    models:
      "278":
        context_length: 262144
        max_output_tokens: 32768
        supports_vision: false   # 27B Dense 无 mmproj
      "358":
        context_length: 262144
        max_output_tokens: 32768
        supports_vision: true    # 35B MoE 配置 mmproj，处理视觉任务
    # 注意：35xb（APEX I-Balanced）已删除（2026-06-12）
    request_timeout_seconds: 3600  # API 请求超时（与 llama-server --timeout 对齐）
    stale_timeout_seconds: 3600   # 流式停滞检测（必须与 request_timeout 对齐以支持长上下文）

model:
  default: "278"                   # 主力模型：278（27B Dense，质量最高，~13 t/s）
  provider: "custom:local-llm"
  base_url: "https://{your_domain}/v1"
  extra_body:
    chat_template_kwargs:
      enable_thinking: true
max_tokens: 32768                 # 必须 ≥ reasoning-budget + 预期输出

fallback_model:
  provider: custom:local-llm
  model: '278'                     # 与 default 相同；358 可手动切换

agent:
  gateway_timeout: 3600           # Gateway 级超时（与所有其他超时对齐）

streaming:
  enabled: true                  # Gateway Bot 流式输出（editMessage）

compression:
  enabled: true
  threshold: 0.80                # 80% 上下文使用率时触发压缩
  target_ratio: 0.30             # 压缩后保留 30% 阈值作为最近上下文
  protect_last_n: 20             # 永不压缩最近 20 条消息

auxiliary:                         # 所有辅助任务路由到 358（支持视觉的 MoE，~50 t/s）
                                  # 278 = 主力模型（主对话，质量最高）
                                  # 358 = 辅助模型（压缩、视觉等）
                                  # title_generation 使用 278 以避免模型切换开销
  vision:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"   # ⚠️ 必须显式设置——空字符串导致 RuntimeError
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  web_extract:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  compression:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  skills_hub:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  approval:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  mcp:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  title_generation:
    provider: custom:local-llm
    model: '278'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  triage_specifier:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  kanban_decomposer:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  profile_describer:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  curator:
    provider: custom:local-llm
    model: '358'
    base_url: "https://{your_domain}/v1"
    timeout: 3600
    extra_body:
      chat_template_kwargs:
        enable_thinking: false

approvals:
  mode: auto                        # 日常操作自动通过，破坏性操作需确认
  timeout: 3600                     # CLI 审批超时
  gateway_timeout: 3600             # Gateway（QQ Bot）审批超时；未设置时默认仅 300 秒
```

**配置要点：**
- `provider: "custom:local-llm"` — 走命名 providers 解析路径（`"custom"` direct-alias 会忽略 `extra_body`）
- ⚠️ **providers 键必须包含 `custom:` 前缀** — 即 `custom:local-llm`，而非 `local-llm`。若键名与 `model.provider` 不匹配，Hermes 的 `get_provider_request_timeout()` 返回 `None` → 回退到硬编码 `HERMES_STREAM_READ_TIMEOUT = 120s`，导致长上下文请求必定超时。这是级联超时事故的根因（参见已知问题）
- `key_env: "DASHENZHIYAN_API_KEY"` — 需在 `~/.hermes/.env` 中设置
- `supports_vision: false` 在 278（27B Dense 无 mmproj）；`supports_vision: true` 在 358（35B MoE 配置 mmproj）
- 35xb（APEX I-Balanced）已删除（2026-06-12）— 不再在 Hermes 或 llama-server 中注册
- `max_tokens: 32768` — 必须 ≥ reasoning-budget (16384) + 预期输出；8192 不够
- `chat_template_kwargs: enable_thinking: true` — 启用思考模式；省略或设 `false` 关闭
- `context_length` 是每 slot 上下文（ctx-size ÷ parallel），不是总 ctx-size
- `stale_timeout_seconds: 3600` — 必须与 `request_timeout_seconds` 对齐以支持长上下文 prefill（>1000s）
- `gateway_timeout: 3600` — Gateway 级超时与所有其他超时对齐
- `auxiliary` — 11 个辅助任务全部统一路由到 358（支持视觉的 MoE，~50 t/s）；`enable_thinking: false` 降低延迟；`timeout: 3600` 与全链路超时对齐
- `auxiliary.vision.base_url` — ⚠️ **必须显式设置**为 `https://{your_domain}/v1`。空字符串会导致 `resolve_vision_provider_client()` 跳过显式分支 → RuntimeError。非视觉辅助任务空字符串正常（不同代码路径）。参见已知问题。
- `approvals.mode: auto` — 日常操作（文件读取、工具调用）自动通过，仅破坏性操作（删文件、危险命令）需手动确认。设为 `manual` 时 QQ Bot 每次工具调用都弹确认，体验很差
- `approvals.timeout: 3600` — CLI 审批最长等待时间
- `approvals.gateway_timeout: 3600` — ⚠️ **Gateway（QQ Bot）审批超时**，与 `timeout` 是独立字段；未设置时默认仅 300 秒（5 分钟），消息平台用户常需更长时间响应，必须显式设置

**环境变量覆盖**（`~/.hermes/.env`）：

```bash
# 覆盖 Hermes 硬编码默认值——防止长上下文在 120s/180s 超时
HERMES_STREAM_READ_TIMEOUT=3600
HERMES_STREAM_STALE_TIMEOUT=7200


```

**使用方式：**
```bash
wsl                                    # 进入 WSL
hermes                                 # TUI 模式（交互式）
hermes -z '快速问题'                    # oneshot 模式
hermes -z '问题' --model 358            # 切换到辅助模型的 oneshot
```

**TUI 常用命令：** `/model 358` 切换模型、`/skills` 查看技能、`/help` 全部命令、`Ctrl+C` 中断回复、`Ctrl+D` 或 `/exit` 退出。

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
- [ ] `~/model/router-preset.ini` 配置正确（活跃模型参数 + alias：278/358；35xb/35xq/276/274 已删除）
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回模型 + aliases
- [ ] 双模型常驻模式：启动后 278 和 358 均 status `loaded`，各自独立 slot
- [ ] 单模型模式（QClaw）：模型通过 LRU 按请求切换（冷加载 8–17 秒）
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

**状态：** 已解决——从服务配置中移除 `--sleep-idle-seconds`

**受影响场景：** 旧版双模型常驻模式（`models-max 2`）下，多个模型共存 + `--sleep-idle-seconds` 触发空闲卸载→重载循环，导致内存尖峰 OOM。**此场景已废弃——当前使用单模型轮换模式（models-max 1），且已删除多余模型（274, 35xb 等），仅有 278 和 358 两个模型。**

**现象：** 运行数小时后 Linux OOM killer 终止 `llama-server`。

**根因链条：**
1. `--sleep-idle-seconds` 空闲卸载模型释放内存
2. 下次请求触发冷重载 → 模型权重从磁盘读入 + `mlock` 锁定到 RAM
3. 冷重载期间多模型共存于内存
4. `parallel > 1` 导致大量 KV cache 预分配 + prompt cache 累积
5. 冷重载内存尖峰超过物理 RAM + swap → OOM Kill

**关键发现：** 不加 `--sleep-idle-seconds`，已加载的模型会保持常驻。空闲卸载/重载循环才是 OOM 的根因。

**解决方案：**
- 从服务配置中移除 `--sleep-idle-seconds`（已实施）
- 切换至单模型轮换模式（`models-max 1`），同一时刻仅一个模型在内存中
- 删除多余模型文件（274/276/35xb/35xq 已全部删除）
- 固定 `parallel = 1` 避免不必要的 KV cache 预分配

### `reasoning=off` 导致 APEX I-Quality checkpoint 恢复灾难性变慢

**状态：** 已修复——从 35xq preset 中移除 `reasoning = off` 和 `reasoning-budget = 0`，替换为 `reasoning-budget = 8192`

**受影响模型：** 仅 35B-A3B APEX I-Quality（别名 `35xq`，已删除）。其他模型（358/278）不受影响。

**现象：** 35xq 的第一次请求正常（<0.5s），但后续请求耗时 43–75 秒。服务端看似卡死——数十秒无输出，然后以 ~1 t/s 缓慢返回。

**根因：** `reasoning = off` 导致 checkpoint 保存时的 attention mask 与运行时配置不匹配。当 llama-server 尝试恢复 prompt cache checkpoint 时，检测到不一致，回退到慢路径——重新 prefill checkpoint 中的所有 token，而非直接加载 KV cache 快照。

**证据：**

| 配置 | Prefill 速度 | Checkpoint 恢复 |
|------|-------------|----------------|
| `reasoning=off`（异常） | 0.37–0.95 t/s | 43–75s ❌ |
| `reasoning-budget=8192`（正常） | 118–129 t/s | <0.1s ✅ |

其他开启 reasoning 的 MoE 模型（358）无 checkpoint 问题。仅 `reasoning=off` + APEX I-Quality 的组合触发此 bug。

**修复：** 从 35xq preset section 中移除 `reasoning = off` 和 `reasoning-budget = 0`。使用 `reasoning-budget = 8192`（与其他模型一致）。如不需要 thinking 输出，在 API 请求体中设置 `chat_template_kwargs: { enable_thinking: false }`。

**警告：** 不要重新添加 `reasoning = off`。这是发现的第三个 reasoning 相关 bug（前两个：`reasoning-format=none` 导致重复输出，`reasoning=off` 导致 checkpoint 恢复失败）。安全做法是在服务端始终开启 reasoning，在请求层面控制。

---

### MTP + 量化 KV cache 触发 Vulkan DeviceLost（b9318+）

**状态：** 部分解决——已升级至 b9592（F16 KV 安全），量化 KV + Vulkan + MTP 仍不可用；等待上游修复

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

**Workaround：** 已升级至 b9592（当前使用 F16 KV 不触发此 bug）。在上游修复 Vulkan + 量化 KV cache 交互前**不要**启用量化 KV 类型。

**上游追踪：** 尚未提交 issue。此回归仅影响 Vulkan 后端 + MTP + 量化 KV；其他后端（CPU/CUDA/Metal）不受影响。

---

### `--cache-ram -1` 导致 VRAM 争抢和 35B 冷加载卡死

**状态：** 已缓解——prompt cache 现在在 INI 中每模型配置（278 `cache-ram = 16384`，358 `cache-ram = 4096`），不再使用服务级 `--cache-ram -1`

**受影响场景：** 旧版双模型常驻模式下 `--cache-ram -1` 导致无限 prompt cache 增长，挤占冷加载的模型内存。

**现象：** 27B 模型先运行并累积了大量 prompt cache 后，后续请求 35B 模型触发冷加载，在 "fitting params to device memory" 阶段卡死 20+ 分钟。

**根因链：**
1. `--cache-ram -1` 允许 prompt cache 无限增长（Vulkan 统一内存上最多 ~30 checkpoints × ~400 MB 每个）
2. 处理长上下文请求后，prompt cache 占用大量内存，剩余空间不足
3. 请求其他模型时，必须在剩余内存中装入模型权重
4. prompt cache 耗尽空闲内存后，加载过程进入紧密分配重试循环

**证据（来自日志）：**
- 35B 冷加载正常情况（内存充足）：~14 秒
- 35B 冷加载内存被 prompt cache 占满时（`--cache-ram -1`）：20–28 分钟
- 移除 `-1` 后：加载正常完成，swap 从 10 GiB 降至 256 KiB

**当前缓解措施：**
- 切换至单模型轮换模式（`--models-max 1`），同一时刻仅一个模型在内存中
- Prompt cache 在 INI 中每模型配置为固定上限（278 `cache-ram = 16384`，358 `cache-ram = 4096`），防止无限增长
- 配合 `--slot-save-path` KV checkpoint 保存/恢复
- GTT 120GB + mlock=1 确保模型权重常驻物理内存
- **切勿**使用 `--cache-ram -1`（无限制）

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

**状态：** 已修复——providers 键从 `local-llm` 改为 `custom:local-llm`

**受影响场景：** Hermes 配置中 `model.provider = "custom:local-llm"` 但 `providers` 字典键为 `local-llm`（缺少 `custom:` 前缀）。

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

*测试环境：{your_machine} · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9592 Vulkan · 2026-06-03 · 更新于 2026-06-13（双模型 ubatch=256; INI: kv-unified=1, cache-ram=16384/4096, reasoning-budget=16384, slot-prompt-similarity=0.8, 采样参数; systemd: wrapper 脚本 + ExecStartPost checkpoint 恢复; models-max 2; Hermes: title_generation→278）*
