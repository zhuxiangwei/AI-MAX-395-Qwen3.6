#!/usr/bin/env python3
"""
监控播报系统 v2 - LLM Log Monitor + Hardware Speaker

双频率轮询：
  - 快速轮询 (30s): 模型切换 + 推理任务状态变化（开始/prefill完成/结束/空闲）
  - 慢速轮询 (300s): 硬件告警 + 日志 E/F 级别 + 日常播报

TTS 缓冲队列：播报中时新消息排队，按优先级发送。
"""
import json
import os
import random
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ============ 配置 ============
LOG_DIR = Path("/home/zxw/logs")
ROUTER_LOG = LOG_DIR / "llama" / "router.log"
GPU_TEMP_LOG = LOG_DIR / "gpu-temp.log"
STATE_FILE = Path("/home/zxw/.config/monitor-broadcast/state.json")
TTS_URL = "http://127.0.0.1:9900/v1/tts"
TTS_SPEAKER = 3061
TTS_VOLUME = 0.3          # 30% 音量

FAST_POLL = 30            # 快速轮询 30s（模型切换 + 任务状态）
SLOW_POLL = 300           # 慢速轮询 300s（硬件 + 日志告警 + 日常）
COOLDOWN = 300            # 非严重告警全局冷却 5 分钟
ALERT_DEDUP = 300         # 同类严重告警去重 5 分钟
DAILY_INTERVAL = 3600     # 日常播报 1 小时

# ============ 硬件阈值 ============
GPU_TEMP_WARN = 85
GPU_TEMP_CRIT = 92
MEM_WARN_PCT = 92
MEM_CRIT_PCT = 97
GPU_PWR_HIGH = 120

# ============ 日志关键字告警 ============
ALERT_KEYWORDS = [
    (re.compile(r'(?i)out.of.memory|OOM|cannot.allocate'), "oom", 3),
    (re.compile(r'(?i)xid'), "xid_error", 3),
    (re.compile(r'(?i)segfault|segmentation.fault'), "segfault", 3),
    (re.compile(r'(?i)DeviceLost|vk::.*Error|vulkan.*fail'), "vulkan_crash", 3),
    (re.compile(r'(?i)child.*crash|child.*exit|defunct|killed.*child'), "child_crash", 3),
    (re.compile(r'\] \d+\.\d+\.\d+\.\d+ F '), "fatal", 3),
    (re.compile(r'\] \d+\.\d+\.\d+\.\d+ E '), "error", 2),
]

# ============ 任务/模型正则 ============
# [PORT] TIMESTAMP I slot launch_slot_: id  0 | task 52073 | processing task, is_child = 0
TASK_LAUNCH_RE = re.compile(r'launch_slot_.*?task\s+(\d+)')
# [PORT] TIMESTAMP I slot      release: id  0 | task 52073 | stop processing: n_tokens = 104437
TASK_RELEASE_RE = re.compile(r'release:.*?task\s+(\d+).*?n_tokens\s*=\s*(\d+)')
# [PORT] TIMESTAMP I slot print_timing: id  0 | task 52073 | prompt eval time =     931.84 ms /   217 tokens
TASK_PREFILL_RE = re.compile(r'print_timing.*?task\s+(\d+).*?prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens')
# [PORT] TIMESTAMP I slot print_timing: id  0 | task 52073 | n_decoded =   6630, tg =  50.15 t/s
TASK_GEN_RE = re.compile(r'print_timing.*?task\s+(\d+).*?n_decoded\s*=\s*(\d+).*?tg\s*=\s*([\d.]+)')
# all slots are idle
TASK_IDLE_RE = re.compile(r'all slots are idle')
# proxying request to model Qwen3.6-35B-A3B-UD-Q8_K_XL on port 60425
MODEL_PROXY_RE = re.compile(r'proxying request to model\s+(.+?)\s+on port\s+(\d+)')

# gpu-temp.log 格式
GPU_TEMP_LOG_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*'
    r'GPU\s+(\d+)°C.*?'
    r'\|\s*(\d+)%\s*busy\s*\|\s*'
    r'(\d+)W\s*\|\s*'
    r'RAM\s+([\d.]+)/([\d.]+)GB'
)

# ============ 全局退出标志 ============
_running = True


def _handle_sigterm(signum, frame):
    global _running
    _running = False
    print(f"[Monitor] 收到信号 {signum}，准备退出...")


# ============ 播报文案 ============
class BroadcastTexts:
    OOM = ["严重警告！显存溢出！", "紧急！OOM 告警！"]
    XID_ERROR = ["显卡报错！Xid 错误！", "检测到 Xid 错误！"]
    CRITICAL = ["紧急告警！严重错误！", "Critical 错误！"]
    SEGFAULT = ["段错误！进程可能崩溃！", "Segmentation Fault！"]
    FATAL = ["致命错误！", "Fatal 告警！"]
    VULKAN_CRASH = ["Vulkan 崩溃！", "GPU 驱动异常！"]
    CHILD_CRASH = ["子进程崩溃！", "推理进程异常退出！"]
    ERROR = ["检测到错误日志。", "出现 Error。"]
    HW_GPU_TEMP_CRIT = ["GPU 温度严重告警！{temp} 度！", "GPU 过热！{temp} 度！"]
    HW_GPU_TEMP_WARN = ["GPU {temp} 度，温度偏高。", "GPU 温度 {temp} 度。"]
    HW_GPU_PWR_HIGH = ["GPU 功耗 {watt}W。", "GPU 功率 {watt}W。"]
    HW_MEM_CRIT = ["内存严重不足！{pct}%！", "内存快满了，{pct}%！"]
    HW_MEM_WARN = ["内存使用偏高，{pct}%。", "内存占用 {pct}%。"]

    # 模型切换
    MODEL_SWITCH = ["模型已切换到 {model}。", "当前模型：{model}。"]

    # 任务状态
    TASK_START = ["新任务 {task_id}，开始推理。", "任务 {task_id} 启动。"]
    TASK_PREFILL = ["任务 {task_id}，预填充完成，{tokens} 个 token，速度 {speed} t/s。"]
    TASK_DONE = ["任务 {task_id} 完成，共 {tokens} 个 token。", "任务 {task_id} 结束。"]
    TASK_IDLE = ["所有任务完成，系统空闲。", "空闲了。"]
    TASK_GEN_MILESTONE = ["任务 {task_id} 生成中，已输出 {decoded} token，速度 {speed} t/s。"]

    QUIET = ["一切正常。", "系统运行平稳。", "风平浪静。"]
    BUSY = ["忙着呢。", "有任务在跑。"]

    @classmethod
    def pick(cls, category, **kwargs):
        texts = getattr(cls, category, [])
        if not texts:
            return None
        text = random.choice(texts)
        return text.format(**kwargs) if kwargs else text


# ============ TTS 队列 ============
class TTSQueue:
    """TTS 播报队列，单线程发送，避免并发请求。"""

    def __init__(self):
        self._queue = deque()
        self._lock = threading.Lock()
        self._worker = None
        self._sent_count = 0

    def start(self):
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def put(self, text, priority=0, tag=""):
        """入队。priority 越高越优先。"""
        with self._lock:
            # 严重告警插队到队列头部（但在已有的高优先级之后）
            if priority >= 3:
                # 找到第一个 priority < 3 的位置插入
                idx = 0
                for i, item in enumerate(self._queue):
                    if item[1] < 3:
                        idx = i
                        break
                else:
                    idx = len(self._queue)
                self._queue.insert(idx, (text, priority, tag))
            else:
                self._queue.append((text, priority, tag))
            qsize = len(self._queue)
        print(f"[Queue] +\"{text[:40]}\" (pri={priority}, qsize={qsize})")

    def _run(self):
        while _running:
            item = None
            with self._lock:
                if self._queue:
                    item = self._queue.popleft()
            if item is None:
                time.sleep(1)
                continue
            text, priority, tag = item
            self._speak(text)
            self._sent_count += 1

    def _speak(self, text):
        payload = json.dumps({
            "text": text,
            "speaker": TTS_SPEAKER,
            "volume": TTS_VOLUME,
        }).encode("utf-8")
        req = urllib.request.Request(
            TTS_URL, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                wav = resp.read()
            # 写临时 WAV 文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav)
                wav_path = f.name
            # 用 systemd-run --user --no-block 播放，完全脱离当前进程
            subprocess.run(
                ["systemd-run", "--user", "--no-block",
                 "aplay", "-q", "-D", "plughw:1,0", wav_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"[TTS] OK: \"{text[:50]}\" ({len(wav)} bytes, playing {wav_path})")
            # 延迟清理临时文件（播放需要几秒）
            threading.Thread(
                target=lambda: (time.sleep(15), os.unlink(wav_path)),
                daemon=True,
            ).start()
        except Exception as e:
            print(f"[TTS] FAIL: {e}")

    @property
    def queue_size(self):
        with self._lock:
            return len(self._queue)


# ============ 增量文件读取 ============
def read_new_lines(filepath, offset):
    new_lines = []
    new_offset = offset
    try:
        size = filepath.stat().st_size
        if size < offset:
            offset = 0
        if size == offset:
            return [], size
        with open(filepath, "r", errors="replace") as f:
            f.seek(offset)
            content = f.read()
            new_offset = f.tell()
        new_lines = content.splitlines()
    except FileNotFoundError:
        pass
    except IOError as e:
        print(f"[READ] {filepath}: {e}")
    return new_lines, new_offset


# ============ router.log 分析（快速轮询：模型+任务）============
def analyze_router_fast(lines, state):
    """快速轮询分析：模型切换 + 任务状态变化。返回播报列表 [(text, priority, tag)]"""
    broadcasts = []
    current_model = state.get("current_model", "")
    current_port = state.get("current_port", "")

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # 模型切换检测
        m = MODEL_PROXY_RE.search(s)
        if m:
            model_name = m.group(1)
            port = m.group(2)
            if model_name != current_model or port != current_port:
                current_model = model_name
                current_port = port
                state["current_model"] = current_model
                state["current_port"] = current_port
                # 简化模型名
                short = model_name.replace("Qwen3.6-", "").replace("-UD-Q8_K_XL", "")
                text = BroadcastTexts.pick("MODEL_SWITCH", model=short)
                if text:
                    broadcasts.append((text, 1, "model_switch"))
            continue

        # 任务启动
        m = TASK_LAUNCH_RE.search(s)
        if m:
            task_id = int(m.group(1))
            state["_active_task"] = task_id
            text = BroadcastTexts.pick("TASK_START", task_id=task_id)
            if text:
                broadcasts.append((text, 1, "task_start"))
            continue

        # Prefill 完成
        m = TASK_PREFILL_RE.search(s)
        if m:
            task_id = int(m.group(1))
            ms = float(m.group(2))
            tokens = int(m.group(3))
            speed = tokens / (ms / 1000) if ms > 0 else 0
            text = BroadcastTexts.pick("TASK_PREFILL",
                                       task_id=task_id, tokens=tokens, speed=f"{speed:.0f}")
            if text:
                broadcasts.append((text, 1, "task_prefill"))
            continue

        # 生成进度（只在里程碑播报：每 5000 token）
        m = TASK_GEN_RE.search(s)
        if m:
            task_id = int(m.group(1))
            decoded = int(m.group(2))
            tg = float(m.group(3))
            last_milestone = state.get("_last_gen_milestone", 0)
            milestone = (decoded // 5000) * 5000
            if milestone > last_milestone and milestone > 0:
                state["_last_gen_milestone"] = milestone
                text = BroadcastTexts.pick("TASK_GEN_MILESTONE",
                                           task_id=task_id, decoded=decoded, speed=f"{tg:.1f}")
                if text:
                    broadcasts.append((text, 0, "task_gen"))
            continue

        # 任务结束
        m = TASK_RELEASE_RE.search(s)
        if m:
            task_id = int(m.group(1))
            n_tokens = int(m.group(2))
            state["_active_task"] = None
            state["_last_gen_milestone"] = 0
            text = BroadcastTexts.pick("TASK_DONE", task_id=task_id, tokens=n_tokens)
            if text:
                broadcasts.append((text, 1, "task_done"))
            continue

        # 空闲
        if TASK_IDLE_RE.search(s):
            if state.get("_active_task") is not None:
                state["_active_task"] = None
                state["_last_gen_milestone"] = 0
                text = BroadcastTexts.pick("TASK_IDLE")
                if text:
                    broadcasts.append((text, 0, "task_idle"))

    return broadcasts


# ============ router.log 分析（慢速轮询：告警）============
def analyze_router_slow(lines):
    """慢速轮询分析：E/F 级别告警 + 关键字。返回告警列表"""
    alerts = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        for pattern, atype, sev in ALERT_KEYWORDS:
            if pattern.search(s):
                alerts.append({"type": atype, "severity": sev, "line": s[:200]})
                break
    return alerts


# ============ gpu-temp.log 分析 ============
def parse_gpu_temp_line(line):
    m = GPU_TEMP_LOG_RE.search(line)
    if not m:
        return None
    return {
        "timestamp": m.group(1),
        "gpu_temp": int(m.group(2)),
        "gpu_busy": int(m.group(3)),
        "gpu_pwr": int(m.group(4)),
        "mem_used_gb": float(m.group(5)),
        "mem_total_gb": float(m.group(6)),
    }


def analyze_gpu_temp_lines(lines):
    alerts = []
    for line in lines:
        data = parse_gpu_temp_line(line)
        if not data:
            continue
        line_alerts = []
        t = data["gpu_temp"]
        if t >= GPU_TEMP_CRIT:
            line_alerts.append({"type": "hw_gpu_temp_crit", "severity": 3, "temp": t})
        elif t >= GPU_TEMP_WARN:
            line_alerts.append({"type": "hw_gpu_temp_warn", "severity": 1, "temp": t})
        p = data["gpu_pwr"]
        if p >= GPU_PWR_HIGH:
            line_alerts.append({"type": "hw_gpu_pwr_high", "severity": 1, "watt": p})
        mem_pct = data["mem_used_gb"] / data["mem_total_gb"] * 100
        if mem_pct >= MEM_CRIT_PCT:
            line_alerts.append({"type": "hw_mem_crit", "severity": 3, "pct": mem_pct})
        elif mem_pct >= MEM_WARN_PCT:
            line_alerts.append({"type": "hw_mem_warn", "severity": 1, "pct": mem_pct})
        if line_alerts:
            line_alerts.sort(key=lambda a: -a["severity"])
            alerts.append(line_alerts[0])
    return alerts


# ============ 状态管理 ============
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                s = json.load(f)
            if isinstance(s.get("active_tasks"), list):
                s["active_tasks"] = set(s["active_tasks"])
            return s
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "file_offsets": {},
        "last_broadcast_time": 0,
        "last_broadcast_type": "",
        "active_tasks": set(),
        "total_launched": 0,
        "completed_tasks": 0,
        "alert_cooldown": {},
        "current_model": "",
        "current_port": "",
    }


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in state.items() if not k.startswith("_")}
        data["active_tasks"] = list(state.get("active_tasks", set()))
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"[STATE] 保存失败: {e}")


# ============ 慢速轮询播报决策 ============
def decide_slow_broadcast(alerts, state):
    """慢速轮询的告警决策，返回 (text, tag) 或 None"""
    now = time.time()
    cooldown_ok = (now - state["last_broadcast_time"]) >= COOLDOWN

    # P1: 严重告警（不受 cooldown）
    critical = [a for a in alerts if a["severity"] == 3]
    if critical:
        alert = critical[0]
        atype = alert["type"]
        last = state["alert_cooldown"].get(atype, 0)
        if (now - last) >= ALERT_DEDUP:
            text_map = {
                "oom": ("OOM", {}),
                "xid_error": ("XID_ERROR", {}),
                "segfault": ("SEGFAULT", {}),
                "fatal": ("FATAL", {}),
                "vulkan_crash": ("VULKAN_CRASH", {}),
                "child_crash": ("CHILD_CRASH", {}),
                "hw_gpu_temp_crit": ("HW_GPU_TEMP_CRIT", {"temp": alert.get("temp", "?")}),
                "hw_mem_crit": ("HW_MEM_CRIT", {"pct": f"{alert.get('pct', 0):.0f}"}),
            }
            category, kwargs = text_map.get(atype, ("CRITICAL", {}))
            text = BroadcastTexts.pick(category, **kwargs)
            if text:
                state["alert_cooldown"][atype] = now
                return text, atype

    if not cooldown_ok:
        return None, ""

    # P2: 一般错误
    errors = [a for a in alerts if a["severity"] == 2]
    if errors:
        return BroadcastTexts.pick("ERROR"), "error"

    # P3: 硬件警告
    hw_warns = [a for a in alerts if a["severity"] == 1 and a["type"].startswith("hw_")]
    if hw_warns:
        alert = hw_warns[0]
        atype = alert["type"]
        hw_map = {
            "hw_gpu_temp_warn": ("HW_GPU_TEMP_WARN", {"temp": alert.get("temp", "?")}),
            "hw_gpu_pwr_high": ("HW_GPU_PWR_HIGH", {"watt": alert.get("watt", "?")}),
            "hw_mem_warn": ("HW_MEM_WARN", {"pct": f"{alert.get('pct', 0):.0f}"}),
        }
        category, kwargs = hw_map.get(atype, ("HW_MEM_WARN", {}))
        text = BroadcastTexts.pick(category, **kwargs)
        if text:
            return text, atype

    # P4: 日常播报
    if (now - state.get("last_broadcast_time", 0)) >= DAILY_INTERVAL:
        active = bool(state.get("active_tasks"))
        text = BroadcastTexts.pick("BUSY" if active else "QUIET")
        if text:
            return text, "daily"

    return None, ""


# ============ 主循环 ============
def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    print(f"[Monitor] 启动监控播报系统 v2")
    print(f"[Monitor] 快速轮询: {FAST_POLL}s (模型+任务) | 慢速轮询: {SLOW_POLL}s (硬件+告警)")
    print(f"[Monitor] TTS: {TTS_URL} speaker={TTS_SPEAKER} volume={TTS_VOLUME}")
    print(f"[Monitor] 日志: {ROUTER_LOG}")
    print(f"[Monitor] 硬件: {GPU_TEMP_LOG}")

    state = load_state()
    offsets = state.get("file_offsets", {})

    # 首次启动：从文件末尾开始
    for fpath in [ROUTER_LOG, GPU_TEMP_LOG]:
        fp = str(fpath)
        if fp not in offsets:
            try:
                offsets[fp] = fpath.stat().st_size
                print(f"[Monitor] {fpath.name}: 从末尾开始 (offset={offsets[fp]})")
            except FileNotFoundError:
                offsets[fp] = 0
                print(f"[Monitor] {fpath.name}: 不存在")
    state["file_offsets"] = offsets

    # 初始化运行时状态
    state["_active_task"] = None
    state["_last_gen_milestone"] = 0

    # 启动 TTS 队列
    tts = TTSQueue()
    tts.start()

    fast_counter = 0  # 用于触发慢速轮询

    while _running:
        try:
            # ---- 快速轮询：router.log（模型+任务）----
            fp = str(ROUTER_LOG)
            offset = state["file_offsets"].get(fp, 0)
            new_lines, new_offset = read_new_lines(ROUTER_LOG, offset)
            if new_lines:
                state["file_offsets"][fp] = new_offset
                fast_broadcasts = analyze_router_fast(new_lines, state)
                for text, pri, tag in fast_broadcasts:
                    tts.put(text, priority=pri, tag=tag)
                    state["last_broadcast_time"] = time.time()
                    state["last_broadcast_type"] = tag
                if fast_broadcasts:
                    print(f"[Fast] {ROUTER_LOG.name}: {len(fast_broadcasts)} 播报")

            # ---- 慢速轮询（每 SLOW_POLL/FAST_POLL 次快速轮询触发一次）----
            if fast_counter >= SLOW_POLL // FAST_POLL:
                fast_counter = 0

                all_alerts = []

                # router.log 告警分析（复用同一文件的增量）
                # 注意：快速轮询已经更新了 offset，这里不需要再读
                # 我们用上一轮快速轮询的行做告警分析
                # 方案：慢速轮询单独维护一个 offset
                slow_fp = str(ROUTER_LOG) + ":slow"
                slow_offset = state["file_offsets"].get(slow_fp, state["file_offsets"].get(fp, 0))
                slow_lines, slow_new_offset = read_new_lines(ROUTER_LOG, slow_offset)
                if slow_lines:
                    state["file_offsets"][slow_fp] = slow_new_offset
                    alerts = analyze_router_slow(slow_lines)
                    all_alerts.extend(alerts)
                    if alerts:
                        print(f"[Slow] {ROUTER_LOG.name}: {len(alerts)} 告警")

                # gpu-temp.log
                fp_gpu = str(GPU_TEMP_LOG)
                offset_gpu = state["file_offsets"].get(fp_gpu, 0)
                gpu_lines, gpu_new_offset = read_new_lines(GPU_TEMP_LOG, offset_gpu)
                if gpu_lines:
                    state["file_offsets"][fp_gpu] = gpu_new_offset
                    hw_alerts = analyze_gpu_temp_lines(gpu_lines)
                    all_alerts.extend(hw_alerts)
                    if hw_alerts:
                        print(f"[Slow] {GPU_TEMP_LOG.name}: {len(hw_alerts)} 告警")

                # 播报决策
                text, btype = decide_slow_broadcast(all_alerts, state)
                if text:
                    pri = 3 if any(a["severity"] == 3 for a in all_alerts if a["type"] == btype) else 1
                    tts.put(text, priority=pri, tag=btype)
                    state["last_broadcast_time"] = time.time()
                    state["last_broadcast_type"] = btype

            save_state(state)
            fast_counter += 1

        except Exception as e:
            print(f"[Error] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

        if _running:
            for _ in range(FAST_POLL):
                if not _running:
                    break
                time.sleep(1)

    # 优雅退出
    save_state(state)
    print("[Monitor] 已退出")


if __name__ == "__main__":
    main()
