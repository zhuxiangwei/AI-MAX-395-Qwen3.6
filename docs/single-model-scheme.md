# 单模型轮换方案 (models-max=1 + parallel=1 + slot save/restore)

## 状态：方案设计完成，待测试（2026-06-04 晚上）

## 为什么 parallel=1

- 双模型常驻 (models-max=2) 下，parallel=1 确保每模型独占一个 slot
- 27B Dense 模型 parallel≥3 触发 Vulkan 崩溃（已知问题）
- 单用户场景下 parallel=1 足够

## 方案概述

当前双模型常驻（278 + 35b）占用 ~62 GB GTT，留 ~34 GB 余量。切换到单模型轮换：

1. `models-max=1`，同一时刻只加载一个模型
2. 客户端请求不同模型时，llama-server 自动 LRU 卸载/加载
3. 保留 KV cache checkpoint（slot save/restore），加速模型切换

## 切换开销估算

### 模型加载时间（纯加载，无 KV cache）

| 模型 | 大小 | 加载时间 |
|------|------|----------|
| 278 (27B Q8) | ~33 GB | ~3.7s |
| 35b (35B APEX) | ~24 GB | ~5.1s |
| 358 (35B Q8) | ~37 GB | ~4.2s |

### KV cache checkpoint 恢复

- F16 KV, ctx=262144: checkpoint 文件 ~4 GB
- 恢复时间: <0.3s（SSD 顺序读）
- Q8_0 KV, ctx=262144: checkpoint 文件 ~2 GB

### 总切换延迟

- 理想情况（有 checkpoint）: ~4-5s (模型加载) + ~0.3s (KV restore) ≈ **5-6s**
- 冷启动（无 checkpoint）: ~4-5s (模型加载) + prefill ≈ 5s + prefill

## 内存占用

单模型模式内存占用：

| 模型 | GTT (加载) | KV cache (262K ctx) | 总计 |
|------|-----------|---------------------|------|
| 278 | ~33 GB | ~7 GB (Q8_0) | ~40 GB |
| 35b | ~24 GB | ~7 GB (F16) | ~31 GB |
| 358 | ~37 GB | ~7 GB (F16) | ~44 GB |

对比双模型常驻: ~62 GB

**节省**: ~22-31 GB，可用于更大模型或更长上下文

## KV Cache 跨模型恢复

### 现状

llama-server 的 KV cache checkpoint 是按模型序列化的。切换模型时：

1. 旧模型 checkpoint 保存到磁盘（`--slot-save-path`）
2. 新模型加载
3. 如果新请求匹配旧 checkpoint → 恢复（`--cache-reuse`）

### 跨模型恢复的可行性

llama-server 当前不支持跨模型 KV cache 恢复。原因：

- KV cache 格式与模型架构强绑定（层数、头数、维度）
- 同架构模型（如 35b/358/35q 都是 35B MoE）理论上可以共享 KV cache
- 不同架构（27B Dense vs 35B MoE）无法共享

### 潜在优化（需修改 llama.cpp）

1. **同架构 KV cache 共享**: 35b ↔ 358 共享 mmproj + 部分 KV cache
2. **前缀缓存独立于模型**: 对相同 prompt 前缀只 prefill 一次
3. **当前方案**: 依赖 `--cache-reuse` 在同模型内复用 KV cache

## 实施步骤

### 1. 修改服务配置

```bash
# llm-router.service
ExecStart=... --models-max 1 --slot-save-path /home/$USER/kv-checkpoints
```

### 2. 确认 INI 配置

所有模型保持 `parallel=1`, `ctx-size=262144`。

### 3. 测试切换延迟

```bash
# 请求 278 → 请求 35b → 请求 278（应有 checkpoint 恢复）
time curl -d '{"model":"278","messages":[...]}' ...
time curl -d '{"model":"35b","messages":[...]}' ...
time curl -d '{"model":"278","messages":[...]}' ...
```

### 4. Hermes 配置

无需修改——Hermes 通过 `model` 字段指定模型，llama-server 自动切换。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 频繁切换导致延迟增加 | auxiliary 全走主模型 278 (provider: auto) |
| KV checkpoint 磁盘占用 | 定期清理（crontab） |
| 切换期间请求排队 | llama-server 内置排队机制 |

## 与当前双模型方案的对比

| 维度 | 双模型常驻 | 单模型轮换 |
|------|-----------|-----------|
| 内存占用 | ~62 GB | ~40 GB |
| 切换延迟 | 0s | ~5-6s |
| auxiliary 延迟 | 即时（35b 独立） | 排队等主模型 |
| 适用场景 | 多模型并发使用 | 单一模型为主 |
