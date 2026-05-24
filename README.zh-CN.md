# Strix Halo LLM 部署 — Qwen3.6

**[English](./README.md)** | **中文**

在 AMD Ryzen AI Max+ 395 (Strix Halo) 上部署 Qwen3.6 系列大模型，使用 llama.cpp + Vulkan，通过 SSH 反向隧道 + 云端 Nginx HTTPS 暴露推理 API。

---

## 性能基准

所有基准测试均在 FEVM faex1 (AMD Ryzen AI Max+ 395, 128 GB LPDDR5X, Radeon 8060S, llama.cpp b9297 Vulkan) 上完成。

### 35B-A3B MoE (Q8_K_XL, 别名 `358`)

**主力模型——生成速度最快，256K 上下文稳定运行。** ✅ *测试完成。*

MoE 每个 token 仅激活 35B 中的 3B 参数 → 生成速度最快。所有速度通过 API `timings` 测量（服务端，排除网络延迟）。Gen 速度含 thinking tokens（真实使用场景）。

**最优配置：** F16 KV cache。**≤128K 用 UB=512**（prefill +14~22%），**256K 用 UB=256**（总耗时 -15%）。Q8_0 KV 对 MoE 无优势——Vulkan FA 反量化开销超过带宽节省。

#### F16 KV UB 扫描

F16 KV cache 在 UB=128/256/512/1024 下测试。所有数据来自 API timings。

**Gen 速度 (t/s)：**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 54.8 | **54.4** | 52.8 | 51.6 |
| p4K | 52.4 | **56.6** | 52.1 | 52.9 |
| p32K | 46.1 | **46.9** | 45.3 | 46.2 |
| p64K | 43.7 | **45.5** | 44.3 | 38.6 |
| p128K | —* | **36.5** | 36.0 | 37.1 |
| p256K | —* | 28.4 | **29.4** | 29.2 |

> *UB=128 p128K/p256K 测试进行中。*

**Prefill 速度 (t/s)：**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 354.4 | 340.2 | **351.9** | 344.4 |
| p4K | 523.2 | 391.3 | 474.2 | **492.7** |
| p32K | 425.1 | **520.1** | 634.4 | **662.1** |
| p64K | 353.7 | 448.1 | **542.2** | 531.9 |
| p128K | —* | **344.6** | 392.5 | 287.1 |
| p256K | —* | **238.2** | 207.8 | 132.3 |

> *UB=128 p128K/p256K 测试进行中。*

**TTFT (秒)：**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 0.449s | **0.37s** | **0.36s** | 0.37s |
| p4K | 14.69s | 10.5s | 8.64s | **8.31s** |
| p32K | 85.9s | 63.0s | 51.65s | **49.49s** |
| p64K | 196.0s | 146.2s | **120.9s** | 123.2s |
| p128K | —* | 380.4s | **333.9s** | 456.5s |
| p256K | —* | **1015.0s** | 1163.6s | 1827.6s |

> *UB=128 p128K/p256K 测试进行中。*

**总执行时间 (秒)：**

| Prompt | UB=128 | UB=256 | UB=512 | UB=1024 |
|--------|--------|--------|--------|--------|
| p128 | 10.79s | **10.23s** | **10.04s** | 11.01s |
| p4K | 33.42s | 28.28s | **27.70s** | 27.99s |
| p32K | 98.51s | 76.01s | **65.17s** | 69.89s |
| p64K | 216.45s | 168.82s | 146.27s | **140.54s** |
| p128K | —* | 406.57s | **356.37s** | 485.81s |
| p256K | —* | **1040.83s** | 1200.3s | 1862.44s |

> *UB=128 p128K/p256K 测试进行中。*

> ⚠️ 总执行时间受 completion token 数量影响（因 thinking token 数量不同而变化）。仅在同一 UB 扫描内对比；不要跨不同测试运行对比总执行时间。Prefill/Gen/TTFT 是稳定指标。

**结论：**

1. **UB=512 在 ≤128K 上下文最优**——prefill +14~22%，TTFT -12~18%
2. **UB=256 在 256K 上下文最优**——p256K prefill 快 13%，TTFT 快 13%
3. **UB=1024 在 p128K+ 严重劣化**——p256K prefill 跌至 132 t/s（-44%），TTFT 膨胀至 1828s（+80% vs UB=256）
4. **UB=128 对 35B MoE 无益**——MTP 命中率从 ~86% 降至 ~65%，拖慢 gen 速度；p32K+ prefill 反而慢于 UB=256/512。与 27B Dense（UB=128 解锁 F16 KV 256K）不同，35B MoE 在 UB=256/512 下已正常工作
5. **Gen 速度跨 UB=256~1024 基本持平**——差异在 1~2 t/s 内；UB=128 因 MTP 退化而较慢
6. **F16 KV 所有 UB 均无 Vulkan 崩溃**——最高 256K 上下文稳定

#### Q8_0 KV Cache + UB 扫描

Q8_0 KV cache 在 3 种 UB 值（512–2048）下测试，对比 F16 KV UB=256 基线。

> 注：本表 F16 ub=256 基线与 Q8_0 数据在同一测试会话中测量（API timings），因此数值可能与上方 F16 KV 主表略有差异（不同会话、客户端测量）。

**Prefill 速度 (t/s)：**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|--------------|--------------|
| p128 | 355.7 | **364.2** | 297.9 | 338.2 |
| p4K | 389.7 | 468.8 | **480.0** | 450.0 |
| p32K | 520.7 | 544.9 | **589.0** | 576.1 |
| p64K | **452.5** | 421.3 | 450.8 | 440.4 |
| p128K | **346.4** | 287.5 | 298.7 | 295.2 |
| p256K | **239.2** | 199.9 | 188.2 | 185.8 |

**Gen 速度 (t/s)：**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|--------------|--------------|
| p128 | **54.8** | 51.6 | 53.5 | 52.5 |
| p4K | **55.1** | 51.3 | 50.2 | 52.7 |
| p32K | 45.4 | 45.3 | **46.1** | 43.9 |
| p64K | **43.8** | 43.7 | 40.7 | 41.2 |
| p128K | **35.6** | 34.0 | 33.3 | 33.3 |
| p256K | **27.7** | 24.3 | 25.4 | 25.9 |

**总执行时间 (秒)：**

| Prompt | F16 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 | Q8_0 ub=2048 |
|--------|-----------|-------------|--------------|--------------|
| p128K | **404** | 477 | 469 | 468 |
| p256K | **1041** | 1352 | 1321 | 1338 |

> UB=2048 p256K 成功完成（Q8_0 KV 降低 VRAM 峰值）。所有 Q8_0 配置在 256K 均不如 F16 KV UB=256。总执行时间 = TTFT + 生成时间。

**结论：**

1. **Q8_0 KV UB=1024 是 Q8_0 配置中的最优**——p4K–p128K prefill 最快，p128K/p256K 总耗时最短
2. **即使最优 Q8_0 配置 (ub=1024) 在 p64K+ 仍不如 F16 ub=256**——prefill -2~21%，gen -7~9%
3. **Q8_0 KV 对 MoE 无优势**——Vulkan FA 反量化开销超过 Q8_0 压缩节省的带宽；MoE 稀疏 KV cache（3B 激活参数）意味着可节省的带宽本就有限
4. **UB=2048 p256K 未崩溃**——Q8_0 KV 降低 VRAM 峰值，但仍不如 F16 KV UB=256
5. **结论：F16 KV UB=512 适合 ≤128K，UB=256 适合 256K。** Q8_0 KV 不推荐用于 35B MoE。

### 27B Dense Q8 (Q8_K_XL, 别名 `278`)

Dense 架构——每 token 激活全部 27B 参数。Gen 速度慢于 Q6/Q4，但 Q8_0 KV cache 可解锁 256K 上下文并大幅提升长上下文 prefill。**推荐配置：Q8_0 KV cache + ub=512**——p64K–p256K 最快，256K 上下文可用（33 分钟 vs 超时）。

**F16 KV cache (ub=256)：**

| Prompt 大小 | Gen 速度 | Prefill 速度 | TTFT |
|-------------|----------|-------------|------|
| 128 tokens | 13.1 t/s | 115.2 t/s | 1.1s |
| 4K tokens | 11.9 t/s | 133.6 t/s | 30.6s |
| 32K tokens | 11.7 t/s | 174.6 t/s | 187.7s |
| 64K tokens | 11.7 t/s | 110.0 t/s | 595.6s |
| 128K tokens | 10.0 t/s | 49.8 t/s | 2633.1s |
| 256K tokens | — | — | ❌ 超时（7200s） |

> 配置：`-c 262144 -b 4096 -ub 256 -t 8`，F16 KV cache，Thinking 已开启。F16 KV 256K 上下文超时 7200s——模型未能在限期内输出首 token。

#### Q8_0 KV Cache + UB 扫描

Q8_0 KV cache 在 3 种 UB 值（256–1024）下测试，对比 F16 KV UB=256 基线。UB≥2048 在 128K+ 上下文崩溃，已排除。

**Prefill 速度 (t/s)：**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128 | 115.2 | 115.8 | 61.1 | 61.0 |
| p4K | 133.6 | 130.1 | 125.2 | 126.3 |
| p32K | 174.6 | 172.3 | **204.9** | **211.9** |
| p64K | 110.0 | 151.1 | **264.3** | 261.8 |
| p128K | 49.8 | 115.8 | **185.1** | 115.3 |
| p256K | ❌ | 80.8 | **138.6** | 136.7 |

**Gen 速度 (t/s)：**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128 | **13.1** | 12.5 | 12.0 | 12.5 |
| p4K | **11.9** | 12.7 | 13.0 | 12.7 |
| p32K | **11.7** | 11.7 | 11.1 | 11.1 |
| p64K | **11.7** | 10.9 | 10.4 | 10.0 |
| p128K | **10.0** | 9.5 | 9.3 | 8.9 |
| p256K | ❌ | **7.2** | 6.8 | 6.7 |

**TTFT (秒)：**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128 | 1.1s | 1.1s | 2.1s | 2.1s |
| p4K | 30.6s | 31.5s | 32.7s | 32.4s |
| p32K | 187.7s | 190.2s | 160.0s | **154.6s** |
| p64K | 595.6s | 433.8s | **248.0s** | 250.4s |
| p128K | 2633.1s | 1132s | **708.3s** | 1136.9s |
| p256K | ❌ | 2994.1s | **1891.4s** | 1917.1s |

**总执行时间 (秒)：**

| Prompt | F16 ub=256 | Q8_0 ub=256 | Q8_0 ub=512 | Q8_0 ub=1024 |
|--------|-----------|-------------|-------------|--------------|
| p128K | 2716 | 1231 | **794** | 1224 |
| p256K | ❌ | 3164 | **1983** | 2040 |

**结论：**

1. **UB=512 是 27B Dense Q8_0 KV 的最优选择**——p64K–p256K TTFT 和总执行时间最短；p64K prefill 比 UB=256 快 75%
2. **UB=1024 仅在 p256K prefill 优于 UB=256**（+69%），但在 p128K TTFT 比 UB=512 慢 60%（1137s vs 708s）
3. **Q8_0 KV 使 256K 上下文可用**——F16 KV 256K 超时；Q8_0 KV UB=512 可在 33 分钟完成
4. **Q8_0 KV 大幅提升长上下文 prefill**——p128K: +271% vs F16 (185 vs 50)；p64K: +140% vs F16 (264 vs 110)
5. **UB≥2048 Vulkan 崩溃**——UB=2048 在 p256K 崩溃；27B Dense VRAM 余量比 35B MoE 更紧张
6. **短 prompt prefill 异常**——Q8_0 KV UB≥512 时 p128 prefill 从 116 骤降至 61 t/s（Vulkan Dense 大 KV cache + 高 UB 走慢路径）

### 27B Dense Q6 (Q6_K_XL, 别名 `276`)

Dense 架构 Q6 量化。**F16 KV cache 在 UB≥512 时 64K+ 上下文 OOM**，但 **UB=128 可解锁 F16 KV 直至 p256K**。**推荐配置：Q8_0 KV cache + ub=512** — 全部 6 个测试点通过，含 p256K，整体最快。**备选：F16 KV + UB=128** — 解锁 p64K–p256K，但比 Q8_0 KV 慢。

#### F16 KV Cache

**UB=512（仅短上下文）：**

| Prompt 大小 | Gen 速度 | Prefill 速度 | TTFT | 状态 |
|-------------|----------|-------------|------|------|
| 128 tokens | 16.5 t/s | 123.3 t/s | 1.03s | ✅ |
| 4K tokens | 16.4 t/s | 129.4 t/s | 31.6s | ✅ |
| 32K tokens | 16.0 t/s | 136.3 t/s | 240.5s | ✅ |
| 64K tokens | — | — | — | ❌ 超时 |
| 128K tokens | — | — | — | ❌ OOM |
| 256K tokens | — | — | — | ❌ OOM |

> 配置：`-c 262144 -b 4096 -ub 512 -t 8`，F16 KV cache。F16 KV + UB=512 在 64K+ 上下文超出 VRAM。

**UB=128 补测（解锁 p64K–p256K）：**

| Prompt | Gen 速度 | Prefill 速度 | TTFT | 总耗时 |
|--------|----------|-------------|------|--------|
| p64K | 13.6 t/s | 163.9 t/s | 423s | 470s |
| p128K | 11.8 t/s | 117.2 t/s | 1158s | 1229s |
| p256K | 9.5 t/s | 44.7 t/s | 5595s | 5671s |

**UB=256 补测：**

| Prompt | Gen 速度 | Prefill 速度 | TTFT | 总耗时 |
|--------|----------|-------------|------|--------|
| p64K | 14.1 t/s | 120.0 t/s | 578s | 651s |
| p128K | 12.7 t/s | 52.4 t/s | 2589s | 2680s |
| p256K | — | — | — | ❌ 超时 |

> **UB=128 发现：** 将 UB 从 512 降至 128 可解锁 F16 KV 在 64K–256K 上下文的使用。UB=128 prefill 比 UB=256 快 27~124%（p64K: 163.9 vs 120.0，p128K: 117.2 vs 52.4）。但 Q8_0 KV UB=512 在 256K 仍优于 F16 KV UB=128（3111s vs 5671s）。

#### Q8_0 KV Cache + UB 扫描

**最优配置：Q8_0 KV + UB=512** — p64K–p256K TTFT 最短，全部 6 点通过。

| Prompt | Q8_0 UB=512 PF | Q8_0 UB=512 Gen | Q8_0 UB=512 TTFT | Q8_0 UB=1024 PF | Q8_0 UB=1024 Gen | Q8_0 UB=1024 TTFT |
|--------|----------------|-----------------|------------------|-----------------|------------------|-------------------|
| p128 | 122.3 | 17.5 | 1.0s | 121.1 | 17.6 | 1.0s |
| p4K | 128.1 | 15.4 | 32.0s | 126.3 | 16.4 | 32.4s |
| p32K | **173.7** | 15.2 | **188.6s** | 176.3 | 15.1 | 185.8s |
| p64K | **151.3** | 13.2 | **433.1s** | 150.8 | 13.0 | 434.6s |
| p128K | **115.3** | 11.6 | **1136.9s** | 113.2 | 12.1 | 1157.4s |
| p256K | **80.2** | 8.0 | **3016.4s** | 78.1 | 8.6 | 3096.2s |

**总执行时间 (秒)：**

| Prompt | Q8_0 UB=512 | Q8_0 UB=1024 |
|--------|-------------|--------------|
| p128K | **1227** | 1239 |
| p256K | **3111** | 3219 |

**结论：**

1. **Q8_0 KV UB=512 是最优选择** — p64K–p256K TTFT 和总执行时间最短
2. **F16 KV UB=512 超过 32K 不可用** — p64K 超时，p128K/p256K OOM
3. **F16 KV UB=128 解锁 p64K–p256K** — 但仍比 Q8_0 KV UB=512 慢（p256K: 5671s vs 3111s）
4. **F16 KV UB=128 vs UB=256** — UB=128 在 p64K+ prefill 快 27~124%，且是唯一跑通 p256K 的 F16 KV 配置
5. **Q8_0 KV UB=512 vs 1024 差异微小** — UB=512 在 p64K+ 略快，UB=1024 在 p32K prefill 略快
6. **256K 上下文 Q8_0 KV 可用** — p256K 约 52 分钟完成 (UB=512)

### 27B Dense Q4 (Q4_K_XL, 别名 `274`)

Dense 架构 Q4 量化——最小模型，生成最快。**F16 KV cache 在 UB=1024 时仅支持到 4K**，但 **UB=128 可解锁 F16 KV 直至 p256K**。**推荐配置：Q8_0 KV cache + ub=1024** — 全部 6 个测试点通过，含 p256K，整体最快。**备选：F16 KV + UB=128** — 解锁 p32K–p256K，但比 Q8_0 KV 慢。

#### F16 KV Cache

**UB=1024（仅短上下文）：**

| Prompt 大小 | Gen 速度 | Prefill 速度 | TTFT | 状态 |
|-------------|----------|-------------|------|------|
| 128 tokens | 23.4 t/s | 145.8 t/s | 0.87s | ✅ |
| 4K tokens | 22.7 t/s | 153.3 t/s | 26.7s | ✅ |
| 32K+ | — | — | — | ❌ OOM |

> 配置：`-c 262144 -b 4096 -ub 1024 -t 8`，F16 KV cache。F16 KV cache 在 32K+ 上下文超出 VRAM 容量。

**UB=128 补测（解锁 p32K–p256K）：**

| Prompt | Gen 速度 | Prefill 速度 | TTFT | 总耗时 |
|--------|----------|-------------|------|--------|
| p32K | 21.4 t/s | 231.2 t/s | 158s | 217s |
| p64K | 19.3 t/s | 194.2 t/s | 357s | 408s |
| p128K | 15.2 t/s | 134.6 t/s | 1008s | 1077s |
| p256K | 12.1 t/s | 47.6 t/s | 5258s | 5325s |

**UB=256 补测：**

| Prompt | Gen 速度 | Prefill 速度 | TTFT | 总耗时 |
|--------|----------|-------------|------|--------|
| p32K | 20.4 t/s | 239.7 t/s | 152s | 204s |
| p64K | 18.7 t/s | 134.8 t/s | 514s | 562s |
| p128K | 15.8 t/s | 55.2 t/s | 2455s | 2490s |
| p256K | — | — | — | ❌ 超时 |

> **UB=128 发现：** 将 UB 从 1024 降至 128 可解锁 F16 KV 在 32K–256K 上下文的使用。UB=128 比 UB=256 在 p64K+ prefill 快 44~144%，且是唯一跑通 p256K 的 F16 KV 配置。但 Q8_0 KV UB=1024 在 p256K 总耗时仍更优（2994s vs 5325s）。

#### Q8_0 KV Cache + UB 扫描

**最优配置：Q8_0 KV + UB=1024** — 全部 6 点通过。UB=2048 在 p128K 之前也可用，但 p256K Vulkan 崩溃。

| Prompt | Q8_0 UB=1024 PF | Q8_0 UB=1024 Gen | Q8_0 UB=1024 TTFT | Q8_0 UB=2048 PF | Q8_0 UB=2048 Gen | Q8_0 UB=2048 TTFT |
|--------|-----------------|------------------|-------------------|-----------------|------------------|-------------------|
| p128 | 145.3 | 23.9 | 0.87s | 148.1 | 24.1 | 0.86s |
| p4K | 155.4 | 25.2 | 26.4s | 147.5 | 23.6 | 27.8s |
| p32K | 206.2 | 20.8 | 158.9s | 204.3 | 20.1 | 160.4s |
| p64K | 171.2 | 17.8 | 382.8s | 171.6 | 18.3 | 381.9s |
| p128K | 123.9 | 14.3 | 1058.0s | 125.6 | 14.6 | 1043.3s |
| p256K | 82.9 | 10.0 | 2916.5s | ❌ | ❌ | ❌ Vulkan 崩溃 |

**Q8_0 KV p256K UB=128 vs UB=256 补测：**

| UB | Prefill | Gen | TTFT | 总耗时 |
|----|---------|-----|------|--------|
| 128 | 78.2 t/s | 10.3 t/s | 3198s | 3276s |
| 256 | 91.1 t/s | 10.5 t/s | 2746s | 2834s |

> Q8_0 KV p256K 中 UB=256 比 UB=128 更快。UB=1024 仍是 Q8_0 KV 全局最优。

**总执行时间 (秒)：**

| Prompt | Q8_0 UB=1024 | Q8_0 UB=2048 |
|--------|--------------|--------------|
| p128K | 1124 | 1100 |
| p256K | **2994** | ❌ 崩溃 |

**结论：**

1. **Q8_0 KV UB=1024 是全局最优配置** — 6 点全部通过，p256K 约 50 分钟
2. **F16 KV UB=1024 超过 p4K 不可用** — 但 UB=128 可解锁 p32K–p256K（见下文）
3. **F16 KV UB=128 解锁 p32K–p256K** — 但 Q8_0 KV UB=1024 在 p256K 仍更优（2994s vs 5325s）
4. **UB=2048 在 p256K Vulkan 崩溃** — 与其他模型相同的 VRAM 限制模式
5. **27B Q4 是最快的 Dense 模型** — gen ~10–25 t/s vs Q6 的 8–18 t/s vs Q8 的 7–13 t/s
6. **UB=128 是 F16 KV 的"解锁键"** — 使 F16 KV 在更高 UB 值 OOM 或超时的上下文长度可用；Q6 同样发现此规律

### 跨模型对比（各模型最优 KV + 最优 UB）

| Prompt | 35B MoE Q8 (UB=512) | 27B Q8 (UB=512) | 27B Q6 (UB=512) | 27B Q4 (UB=1024) |
|--------|---------------------|----------------|-----------------|------------------|
| p128 Gen | 52.8 | 12.0 | 17.5 | 23.9 |
| p4K Gen | 52.1 | 13.0 | 15.4 | 25.2 |
| p32K Gen | 45.3 | 11.1 | 15.2 | 20.8 |
| p64K Gen | 44.3 | 10.4 | 13.2 | 17.8 |
| p128K Gen | 36.0 | 9.3 | 11.6 | 14.3 |
| p256K Gen | 29.4 | 6.8 | 8.0 | 10.0 |
| p256K 总耗时 | 1200s | 1983s | 3111s | 2994s |

> 各模型使用最优配置：35B MoE = F16 KV UB=512（≤128K 最优），27B Q8/Q6 = Q8_0 KV UB=512，27B Q4 = Q8_0 KV UB=1024。Gen 速度含 thinking tokens。35B MoE p256K 使用 UB=256（256K 最优）：gen 28.4 t/s，总耗时 1041s。

---

## 优化参数

### 关键决策及理由

| 决策 | 理由 |
|------|------|
| Service = 服务级，INI = 模型级 | 层次清晰，改模型参数不碰 service 文件 |
| 统一 256K 上下文 | -c 只预分配 KV cache，不影响性能；一套配置覆盖所有 prompt 长度 |
| 按量化等级差异化 ub | 量化越高权重越大，VRAM 余量越小，需更小 ub 保证稳定性；UB=128 可解锁 27B Dense F16 KV 256K 上下文 |
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
| 35B MoE 最大上下文 | 256K | UB=512 ≤128K 最优；UB=256 256K 最优；UB≥2048 在 128K+ 时 Vulkan 崩溃 |
| 27B Dense 最大上下文 | 256K (Q8_0 KV 或 F16 KV UB=128) | 推荐 Q8_0 KV UB=512 (Q8/Q6) / UB=1024 (Q4)；F16 KV UB=128 也可达 256K (Q4/Q6)；F16 KV 默认 UB 在 256K 超时；UB≥2048 崩溃 |
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

[Qwen3.6-27B-UD-Q8_K_XL]
n-gpu-layers = 99
flash-attn = 1
parallel = 1
spec-type = draft-mtp
spec-draft-n-max = 3
mlock = 1
numa = distribute
reasoning-budget = 8192
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
| llama.cpp | b9297 (commit b22ff4b7b, Vulkan 后端) |
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

*测试环境：FEVM faex1 · AMD Ryzen AI Max+ 395 · 128 GB · llama.cpp b9297 Vulkan · 2026-05-24*
