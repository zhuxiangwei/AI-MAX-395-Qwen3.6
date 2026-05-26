# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 暴露推理 API。

---

## 性能基准

所有基准测试均在 FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9299 Vulkan) 上完成。速度通过 API `timings` 测量（服务端，排除网络延迟）。Gen 速度含 thinking tokens。

### 35B-A3B MoE (UD-Q8_K_XL, 别名 `358`)

**主力模型——生成速度最快，256K 稳定运行。** MoE 每 token 仅激活 35B 中的 3B 参数。

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

### 35B-A3B MoE APEX I-Quality (别名 `35q`, ~22 GB)

APEX 量化——针对 MoE 的自适应精度策略。混合精度 per tensor（关键层 Q6_K/Q8_0，中间 expert 层 Q4_K_M）。整体 ~22 GB（按体积介于 Q4~Q5，但质量接近 Q8）。imatrix 多样化校准。**比 UD-Q8+MTP 快 48%，体积仅 59%。**

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

### 35B-A3B MoE APEX I-Balanced (别名 `35b`, ~24 GB)

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

### 27B Dense Q8 (Q8_K_XL, 别名 `278`)

Dense 架构——每 token 激活全部 27B 参数。Q8_0 KV cache 解锁 256K 上下文并大幅提升长上下文 prefill。

**最优配置：Q8_0 KV + UB=512。**

**已排除：** F16 KV（p256K 超时 >7200s）；Q8_0 UB=256（p64K+ 比 UB=512 慢）；Q8_0 UB≥1024（p128K TTFT 在 UB=512 已为 1139s，继续慢化）；UB≥2048（Vulkan 崩溃）。

#### Q8_0 KV UB=512

| Prompt | Gen (t/s) | Prefill (t/s) | TTFT |
|--------|----------|--------------|------|
| p128 | 13.8 | 127.4 | 1.2s |
| p4K | 13.4 | 247.3 | 31.1s |
| p32K | 12.5 | 194.6 | 187.7s |
| p64K | 12.1 | 160.2 | 432.6s |
| p128K | 10.0 | 119.1 | 1139.0s |
| p256K | 7.3 | 82.8 | 3022.3s |

> p128K 总耗时：1272s。p256K 总耗时：3122s（~52 分钟）。Q8_0 KV p128K prefill 比 F16 KV 快 271%（119 vs 32 t/s，F16 KV 基于 b9210 数据）。

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

8 道题覆盖数学、逻辑、计算机科学和哲学。基于关键词匹配评分（每题满分 10，总分 80）。所有模型使用 F16 KV + UB=512 + MTP（`--spec-type draft-mtp --spec-draft-n-max 3`）。

| 题目 | 35q (I-Q) | 35b (I-B) | 358 (Q8) |
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
| 婴儿趴睡 (83 KB) | 939 | 35q | **73.5** | 55.8% | 16.7s |
| | | 35b | 69.6 | 52.4% | 14.6s |
| | | 358 | 51.2 | 50.9% | 18.3s |
| 户外照片 (1.4 MB) | 2059 | 35q | **69.8** | 52.3% | 22.3s |
| | | 35b | 65.4 | 48.4% | 23.4s |
| | | 358 | 49.3 | 48.2% | 28.4s |
| 生日照片 (2.8 MB) | 4034 | 35q | 70.5 | 53.9% | 35.2s |
| | | 35b | **71.1** | 56.6% | 35.2s |
| | | 358 | 53.5 | 55.2% | 39.9s |

> 视觉模式下 MTP 命中率（48–57%）明显低于纯文本模式（60–70%），因为视觉 token 更难预测。APEX I-Quality 视觉生成比 UD-Q8 快约 39%。三个模型均能准确描述图片内容。

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
[Qwen3.6-35B-A3B-APEX-MTP-I-Quality]
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
alias = 35q

[Qwen3.6-35B-A3B-APEX-MTP-I-Balanced]
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
alias = 35b

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
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf` | **35q** | APEX 混合精度 | **MoE** | ~22 GB | 3B |
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced.gguf` | **35b** | APEX 混合精度 | **MoE** | ~24 GB | 3B |
| Qwen3.6-35B-A3B | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | **358** | UD-Q8_K_XL | **MoE** | ~37 GB | 3B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q8_K_XL.gguf` | **278** | UD-Q8_K_XL | Dense | ~33 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q6_K_XL.gguf` | **276** | UD-Q6_K_XL | Dense | ~25 GB | 27B |
| Qwen3.6-27B | `Qwen3.6-27B-UD-Q4_K_XL.gguf` | **274** | UD-Q4_K_XL | Dense | ~17 GB | 27B |

> **别名命名规则：** APEX 模型使用 `35q`/`35b` 表示质量/平衡。UD (Unsloth Dynamic) 量化模型使用 3 位数字 = 模型大小 + 量化等级。API 请求的 `model` 字段使用别名或完整文件名均可。UD 模型来源：[unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF)。

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
    --timeout 3600 \
    --metrics
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
| `/model 35q` | 35B-A3B APEX I-Quality (MoE, 最快生成) |
| `/model 35b` | 35B-A3B APEX I-Balanced (MoE, 最优质量) |
| `/model 358` | 35B-A3B Q8 (MoE, 参考基线) |
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
- [ ] 云端：`curl http://127.0.0.1:8080/v1/models` 返回 6 个模型 + aliases
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

*测试环境：FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9299 Vulkan · 2026-05-26*
