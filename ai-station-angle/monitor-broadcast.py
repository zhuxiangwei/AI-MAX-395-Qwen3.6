#!/usr/bin/env python3
"""
监控播报系统 - LLM Log Monitor Speaker
增量轮询 llama.cpp server 日志目录，检测异常并语音播报。
只关注大模型日志 (Qwen3.6 27B/35B)。
"""
import json
import os
import re
import sys
import time
from pathlib import Path
# ============ 配置 ============
LOG_DIR = Path("/home/zxw/logs")
# 监控的日志文件列表（可扩展）
LOG_FILES = [
    LOG_DIR / "llama" / "router.log",
    LOG_DIR / "llama" / "server.log",
]
STATE_FILE = Path("/home/zxw/.config/systemd/user/monitor-state.json")
TTS_URL = "http://127.0.0.1:9900/v1/tts"
TTS_SPEAKER = 3061
# 播报间隔（秒）
POLL_INTERVAL = 300
# 去重冷却时间（秒）- 相同类型播报不重复
COOLDOWN = 300
# ============ 关键字告警配置 ============
# 按优先级排序，高优先级先匹配
ALERT_KEYWORDS = [
    # (正则, 播报类型, 严重等级 1-3)
    (re.compile(r'(?i)out.of.memory|OOM|cannot.allocate'), "oom", 3),
    (re.compile(r'(?i)xid|Xid'), "xid_error", 3),
    (re.compile(r'(?i)critical'), "critical", 3),
    (re.compile(r'(?i)segfault|segmentation.fault'), "segfault", 3),
    (re.compile(r'(?i)fatal'), "fatal", 3),
    (re.compile(r'(?i)error'), "error", 2),
    (re.compile(r'(?i)warning|warn\b'), "warning", 1),
    # 温度相关
    (re.compile(r'(?i)temp(?:erature)?\s*[=:]\s*(\d+)', re.IGNORECASE), "temperature", 1),
    # 显存相关
    (re.compile(r'(?i)VRAM.*?(\d+\.?\d*)\s*(?:GB|MB)', re.IGNORECASE), "vram", 1),
    (re.compile(r'(?i)kv.cache.*?(\d+\.?\d*)\s*(?:GB|MB)', re.IGNORECASE), "kv_cache", 1),
]
# ============ 任务状态正则 (llama.cpp server) ============
TASK_LAUNCH_RE = re.compile(r'slot\s+launch_slot_completion.*?task\s+(\d+)')
TASK_RELEASE_RE = re.compile(r'slot\s+release:.*?task\s+(\d+)')
TASK_IDLE_RE = re.compile(r'slot\s+update_slots:.*?all slots are idle')
TASK_PROMPT_RE = re.compile(r'slot\s+compute_prompt.*?task\s+(\d+)')
TASK_DECODING_RE = re.compile(r'slot\s+compute_decoding.*?task\s+(\d+)')
# ============ 增量日志读取 ============
def read_new_lines(filepath, offset):
    """从指定 offset 开始读取新内容，返回 (新行列表, 新 offset)"""
    new_lines = []
    try:
        file_size = filepath.stat().st_size
        # 文件被截断/轮转了，重置 offset
        if file_size < offset:
            offset = 0
        if file_size == offset:
            return [], offset
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
# ============ 日志分析 ============
def analyze_lines(lines):
    """分析一批新日志行，返回告警列表和任务状态变化"""
    alerts = []
    task_events = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 1. 关键字告警
        for pattern, alert_type, severity in ALERT_KEYWORDS:
            m = pattern.search(stripped)
            if m:
                alert = {
                    "type": alert_type,
                    "severity": severity,
                    "line": stripped[:200],  # 截断避免过长
                    "groups": m.groups(),
                }
                alerts.append(alert)
                break  # 一行只匹配最高优先级
        # 2. 任务状态
        m = TASK_LAUNCH_RE.search(stripped)
        if m:
            task_events.append({"event": "launch", "task_id": int(m.group(1))})
        m = TASK_PROMPT_RE.search(stripped)
        if m:
            task_events.append({"event": "prompt", "task_id": int(m.group(1))})
        m = TASK_DECODING_RE.search(stripped)
        if m:
            task_events.append({"event": "decoding", "task_id": int(m.group(1))})
        m = TASK_RELEASE_RE.search(stripped)
        if m:
            task_events.append({"event": "release", "task_id": int(m.group(1))})
        if TASK_IDLE_RE.search(stripped):
            task_events.append({"event": "idle"})
    return alerts, task_events
# ============ 播报文案生成 ============
class BroadcastTexts:
    """播报文案库"""
    # --- OOM ---
    OOM = [
        "严重警告！显存溢出，Out of Memory！模型可能崩溃了！",
        "紧急！内存分配失败，OOM 告警！需要立即检查！",
    ]
    # --- Xid Error ---
    XID_ERROR = [
        "显卡报错！Xid 错误出现，硬件可能有问题！",
        "严重！检测到 Xid 错误，GPU 状态异常！",
    ]
    # --- Critical ---
    CRITICAL = [
        "紧急告警！日志出现 Critical 级别错误！",
        "Critical 错误！需要立即关注！",
    ]
    # --- Segfault ---
    SEGFAULT = [
        "严重！段错误！进程可能已崩溃！",
        "Segmentation Fault！程序异常退出！",
    ]
    # --- Fatal ---
    FATAL = [
        "致命错误！Fatal 级别告警！",
        "Fatal 错误出现，服务可能不可用！",
    ]
    # --- Error ---
    ERROR = [
        "检测到错误日志，需要关注。",
        "日志出现 Error，可能有异常情况。",
    ]
    # --- Warning ---
    WARNING = [
        "日志有 Warning，注意观察。",
        "出现警告信息，先关注一下。",
    ]
    # --- 温度 ---
    TEMPERATURE_HIGH = [
        "温度偏高，{temp} 度了，注意散热。",
        "有点热，{temp} 度。",
    ]
    TEMPERATURE_CRIT = [
        "温度告警！{temp} 度，太高了！",
        "高温警告！{temp} 度，需要降温！",
    ]
    # --- 显存 ---
    VRAM_HIGH = [
        "显存占用 {vram}，比较高了。",
        "VRAM 使用 {vram}，注意监控。",
    ]
    KV_CACHE_HIGH = [
        "KV Cache 占用 {cache}，上下文可能快满了。",
        "KV Cache 达到 {cache}，注意上下文长度。",
    ]
    # --- 任务状态 ---
    TASK_LAUNCH = [
        "新任务来了，开始处理。",
        "接单了，有新的推理任务。",
    ]
    TASK_COMPLETE = [
        "任务完成，已释放。",
        "推理结束，收工。",
    ]
    TASK_DECODING = [
        "正在生成回复，别催。",
        "推理中，正在输出 token。",
    ]
    TASK_IDLE = [
        "没事干呢，在摸鱼。",
        "空闲中，等任务呢。",
    ]
    # --- 日常 ---
    QUIET = [
        "一切正常，风平浪静。",
        "系统运行平稳。",
        "安静的一天，没啥事。",
    ]
    BUSY = [
        "任务挺多的，忙起来了。",
        "今天有点忙，请求一个接一个。",
    ]
    @classmethod
    def pick(cls, category, **kwargs):
        texts = getattr(cls, category, [])
        if not texts:
            return None
        text = texts[int(hash(time.monotonic())) % len(texts)]
        return text.format(**kwargs) if kwargs else text
# ============ TTS 调用 ============
def tts_speak(text):
    """通过本地 TTS 服务合成语音，返回是否成功"""
    import urllib.request
    payload = json.dumps({
        "text": text,
        "speaker": TTS_SPEAKER,
        "lang": 2050,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        TTS_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            wav_data = resp.read()
        print(f"[TTS] 合成成功: \"{text[:40]}...\" ({len(wav_data)} bytes WAV)")
        return True
    except Exception as e:
        print(f"[TTS] 失败: {e}")
        return False
# ============ 状态管理 ============
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "file_offsets": {},        # {filepath: offset}
        "last_broadcast_time": 0,
        "last_broadcast_type": "",
        "active_tasks": set(),     # 当前活跃任务 ID
        "completed_tasks": 0,
        "total_launched": 0,
        "alert_cooldown": {},      # {alert_type: last_time}
    }
def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # set 类型不能直接 json 序列化
        save_data = {
            **state,
            "active_tasks": list(state.get("active_tasks", set())),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(save_data, f, indent=2)
    except IOError as e:
        print(f"[STATE] 保存失败: {e}")
# ============ 播报决策 ============
def decide_broadcast(alerts, task_events, state):
    """
    根据告警和任务事件生成播报文案。
    返回 (播报文本, 播报类型) 或 None。
    优先级: OOM/Critical > Error > Warning > 温度 > 显存 > 任务状态 > 日常
    """
    now = time.time()
    cooldown_passed = (now - state["last_broadcast_time"]) > COOLDOWN
    if not cooldown_passed:
        return None, ""
    # --- 优先级1: 严重告警 (severity=3) ---
    critical_alerts = [a for a in alerts if a["severity"] == 3]
    if critical_alerts:
        alert = critical_alerts[0]
        atype = alert["type"]
        # 告警级别去重：同一类型 1 分钟内不重复
        last_alert_time = state["alert_cooldown"].get(atype, 0)
        if (now - last_alert_time) < 60:
            return None, ""
        text_map = {
            "oom": ("OOM", {}),
            "xid_error": ("XID_ERROR", {}),
            "critical": ("CRITICAL", {}),
            "segfault": ("SEGFAULT", {}),
            "fatal": ("FATAL", {}),
        }
        category, kwargs = text_map.get(atype, ("CRITICAL", {}))
        text = BroadcastTexts.pick(category, **kwargs)
        if text:
            state["alert_cooldown"][atype] = now
            return text, atype
    # --- 优先级2: 一般错误 (severity=2) ---
    error_alerts = [a for a in alerts if a["severity"] == 2]
    if error_alerts:
        text = BroadcastTexts.pick("ERROR")
        if text:
            return text, "error"
    # --- 优先级3: 温度告警 ---
    temp_alerts = [a for a in alerts if a["type"] == "temperature"]
    if temp_alerts:
        for a in temp_alerts:
            if a["groups"]:
                temp = int(a["groups"][0])
                if temp >= 85:
                    text = BroadcastTexts.pick("TEMPERATURE_CRIT", temp=temp)
                elif temp >= 75:
                    text = BroadcastTexts.pick("TEMPERATURE_HIGH", temp=temp)
                else:
                    continue
                if text:
                    return text, "temperature"
    # --- 优先级4: 显存/KV Cache ---
    vram_alerts = [a for a in alerts if a["type"] in ("vram", "kv_cache")]
    if vram_alerts:
        for a in vram_alerts:
            if a["groups"]:
                val = a["groups"][0]
                if a["type"] == "vram":
                    text = BroadcastTexts.pick("VRAM_HIGH", vram=f"{val}GB")
                else:
                    text = BroadcastTexts.pick("KV_CACHE_HIGH", cache=f"{val}GB")
                if text:
                    return text, a["type"]
    # --- 优先级5: Warning ---
    warn_alerts = [a for a in alerts if a["severity"] == 1 and a["type"] == "warning"]
    if warn_alerts:
        text = BroadcastTexts.pick("WARNING")
        if text:
            return text, "warning"
    # --- 优先级6: 任务状态 ---
    active_tasks = state.get("active_tasks", set())
    for ev in task_events:
        if ev["event"] == "launch":
            active_tasks.add(ev["task_id"])
            state["total_launched"] = state.get("total_launched", 0) + 1
        elif ev["event"] == "release":
            active_tasks.discard(ev["task_id"])
            state["completed_tasks"] = state.get("completed_tasks", 0) + 1
        elif ev["event"] == "idle":
            if active_tasks:
                # 从忙碌变空闲
                text = BroadcastTexts.pick("TASK_IDLE")
                if text:
                    return text, "task_idle"
    state["active_tasks"] = active_tasks
    # 如果有活跃任务且之前没有
    if active_tasks and not state.get("_prev_active", False):
        text = BroadcastTexts.pick("TASK_LAUNCH")
        if text:
            return text, "task_launch"
    state["_prev_active"] = bool(active_tasks)
    # --- 优先级7: 日常播报（超过 30 分钟无播报）---
    if (now - state.get("last_broadcast_time", 0)) > 1800:
        if active_tasks:
            text = BroadcastTexts.pick("BUSY")
        else:
            text = BroadcastTexts.pick("QUIET")
        if text:
            return text, "daily"
    return None, ""
# ============ 主循环 ============
def main():
    print(f"[Monitor] 启动 LLM 日志监控播报系统")
    print(f"[Monitor] 轮询间隔: {POLL_INTERVAL}s")
    print(f"[Monitor] 监控目录: {LOG_DIR}")
    print(f"[Monitor] 日志文件: {[str(f) for f in LOG_FILES]}")
    state = load_state()
    # 恢复 active_tasks（从 list 转 set）
    if isinstance(state.get("active_tasks"), list):
        state["active_tasks"] = set(state["active_tasks"])
    elif "active_tasks" not in state:
        state["active_tasks"] = set()
    # 初始化文件 offset
    file_offsets = state.get("file_offsets", {})
    for lf in LOG_FILES:
        fp = str(lf)
        if fp not in file_offsets:
            file_offsets[fp] = 0
    state["file_offsets"] = file_offsets
    while True:
        try:
            all_alerts = []
            all_task_events = []
            # 1. 增量读取所有日志文件
            for lf in LOG_FILES:
                fp = str(lf)
                current_offset = state["file_offsets"].get(fp, 0)
                new_lines, new_offset = read_new_lines(lf, current_offset)
                if new_lines:
                    state["file_offsets"][fp] = new_offset
                    alerts, task_events = analyze_lines(new_lines)
                    all_alerts.extend(alerts)
                    all_task_events.extend(task_events)
                    if alerts:
                        print(f"[ALERT] {lf.name}: {len(alerts)} 条告警")
                    if task_events:
                        print(f"[TASK] {lf.name}: {len(task_events)} 个事件")
            # 2. 生成播报
            text, btype = decide_broadcast(all_alerts, all_task_events, state)
            if text:
                print(f"[Broadcast] [{btype}] {text}")
                success = tts_speak(text)
                if success:
                    state["last_broadcast_time"] = time.time()
                    state["last_broadcast_type"] = btype
                else:
                    print(f"[Broadcast] TTS 合成失败，跳过")
            # 3. 保存状态
            save_state(state)
        except Exception as e:
            print(f"[Error] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
        time.sleep(POLL_INTERVAL)
if __name__ == "__main__":
    main()
