#!/usr/bin/env python3
"""
监控播报系统 v8 - LLM Log Monitor + Hardware Speaker

双频率轮询：
  - 快速轮询 (180s): 模型切换 + 推理任务状态变化（开始/prefill完成/结束/空闲）
  - 慢速轮询 (300s): 硬件告警 + 日志 E/F 级别 + 日常播报

TTS 播放策略：
  - 默认非流式模式：完整生成 WAV 后播放（优先稳定性）
  - 流式预缓冲模式保留（_speak_prebuffer），通过 TTS_USE_STREAM 开关切换
  - 所有 TTS 请求强制 language=chinese + ensure_ascii=False
  - 日常播报包含 CPU 负载、GPU 负载、温度、内存信息
  - 任务编号逐位中文朗读

硬件数据源：
  - hw-temp.log（hw-temp.service 持续运行，每 60s 写入一行）
  - 包含 GPU 负载/温度、CPU 温度、NVMe/网卡/WiFi 温度

音量控制（ALSA 系统级）：
  1. ALSA PCM 音量（播放通道）
  2. ALSA Speaker/Headphone（输出通道）
  3. ALSA Master（系统主音量）
  注：TTS API 不支持 volume 参数，音量由 ALSA 系统级控制

自身日志轮转：
  - 使用 logging.handlers.RotatingFileHandler，单个文件 5MB，保留 3 个备份
  - 日志文件: /home/zxw/logs/monitor/monitor.log
"""
import http.client
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ============ 配置 ============
LOG_DIR = Path("/home/zxw/logs")
ROUTER_LOG = LOG_DIR / "llama" / "router.log"
HW_TEMP_LOG = LOG_DIR / "hw-temp.log"
STATE_FILE = Path("/home/zxw/.config/monitor-broadcast/state.json")
MONITOR_LOG_DIR = LOG_DIR / "monitor"
MONITOR_LOG_FILE = MONITOR_LOG_DIR / "monitor.log"
TTS_URL = "http://127.0.0.1:12348/v1/tts"
TTS_SPEAKER = "vivian"    # 中文女声
TTS_SEED = 42             # 固定种子，确保同一文本音色一致
TTS_USE_STREAM = False    # False=非流式(默认,稳定), True=流式预缓冲

# TTS 音频参数
TTS_SAMPLE_RATE = 24000    # 采样率 Hz
TTS_BYTES_PER_SEC = TTS_SAMPLE_RATE * 2  # 16-bit mono = 48000 B/s

FAST_POLL = 180           # 高频轮询 3 分钟（模型切换 + 任务状态）
SLOW_POLL = 300           # 低频轮询 5 分钟（硬件 + 日志告警 + 日常）
COOLDOWN = 300            # 非严重告警全局冷却 5 分钟
ALERT_DEDUP = 300         # 同类严重告警去重 5 分钟
DAILY_INTERVAL = 1800     # 日常播报 30 分钟

# TTS 队列最大长度，超过直接丢弃不入队
TTS_QUEUE_MAX = 3

# HTTP 超时（秒）
HTTP_TIMEOUT = 30

# ============ 硬件阈值 ============
GPU_TEMP_WARN = 80
GPU_TEMP_CRIT = 90
CPU_TEMP_WARN = 80
CPU_TEMP_CRIT = 90
MEM_WARN_PCT = 80
MEM_CRIT_PCT = 90

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
TASK_LAUNCH_RE = re.compile(r'launch_slot_.*?task\s+(\d+)')
TASK_RELEASE_RE = re.compile(r'release:.*?task\s+(\d+).*?n_tokens\s*=\s*(\d+)')
TASK_PREFILL_RE = re.compile(r'print_timing.*?task\s+(\d+).*?prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens')
TASK_GEN_RE = re.compile(r'print_timing.*?task\s+(\d+).*?n_decoded\s*=\s*(\d+).*?tg\s*=\s*([\d.]+)')
TASK_IDLE_RE = re.compile(r'all slots are idle')
MODEL_PROXY_RE = re.compile(r'proxying request to model\s+(.+?)\s+on port\s+(\d+)')

# hw-temp.log 格式:
# 2026-06-24 18:11:42 gpu_busy=100% gpu=71°C cpu=70°C nvme=41°C r8169=51°C eno1=55°C wifi=47°C
HW_TEMP_LOG_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+'
    r'gpu_busy=(\d+)%\s+'
    r'gpu=(\d+)°C\s+'
    r'cpu=(\d+)°C\s+'
    r'nvme=(\d+)°C\s+'
    r'r8169=(\d+)°C\s+'
    r'eno1=(\d+)°C\s+'
    r'wifi=(\d+)°C'
)

# ============ 全局退出标志 ============
_stop_event = threading.Event()


def _handle_sigterm(signum, frame):
    _stop_event.set()
    # 信号处理函数中只使用异步信号安全函数
    os.write(sys.stderr.fileno(), f"[Monitor] 收到信号 {signum}，准备退出...\n".encode())

# ============ 日志配置 ============
def setup_logging():
    """配置日志：同时输出到文件（轮转）和 stderr。"""
    MONITOR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler = RotatingFileHandler(
        MONITOR_LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding='utf-8',
    )
    file_handler.setFormatter(formatter)
    # stderr handler (for systemd journal)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)


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
    HW_GPU_TEMP_CRIT = ["温度严重告警！{temp} 度！", "设备过热！{temp} 度！"]
    HW_GPU_TEMP_WARN = ["温度 {temp} 度，偏高。", "温度 {temp} 度。"]
    HW_CPU_TEMP_CRIT = ["CPU 温度严重告警！{temp} 度！", "CPU 过热！{temp} 度！"]
    HW_CPU_TEMP_WARN = ["CPU 温度 {temp} 度，偏高。", "CPU 温度 {temp} 度。"]
    HW_MEM_CRIT = ["内存严重不足！{pct}%！", "内存快满了，{pct}%！"]
    HW_MEM_WARN = ["内存使用偏高，{pct}%。", "内存占用 {pct}%。"]

    MODEL_SWITCH = ["模型已切换到 {model}。", "当前模型：{model}。"]
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


# ============ 数字转中文朗读 ============
def num_to_chinese(n):
    """将数字逐位转中文，用于任务编号朗读。
    例如 26640 -> 二六六四零
    """
    cn_digits = '零一二三四五六七八九'
    return ''.join(cn_digits[int(d)] for d in str(n))


# ============ 系统状态采集 ============
def get_cpu_load():
    """获取系统负载 (1min)"""
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
        return float(parts[0])
    except Exception:
        return None


def get_system_memory():
    """获取内存使用率"""
    try:
        with open("/proc/meminfo", "r") as f:
            info = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    info[key] = int(parts[1])
        total = info.get("MemTotal", 1)
        available = info.get("MemAvailable", 0)
        used_pct = round((1 - available / total) * 100, 1)
        return used_pct
    except Exception:
        return None


def get_hw_status():
    """从 hw-temp.log 读取最新一行，解析 GPU/CPU/NVMe 等温度 + GPU 负载"""
    try:
        with open(HW_TEMP_LOG, "r") as f:
            lines = f.readlines()
        for line in reversed(lines):
            m = HW_TEMP_LOG_RE.search(line)
            if m:
                return {
                    "gpu_busy": int(m.group(2)),
                    "gpu_temp": int(m.group(3)),
                    "cpu_temp": int(m.group(4)),
                    "nvme_temp": int(m.group(5)),
                    "r8169_temp": int(m.group(6)),
                    "eno1_temp": int(m.group(7)),
                    "wifi_temp": int(m.group(8)),
                }
    except Exception:
        pass
    return None


def build_daily_report():
    """构建日常播报文案（CPU 负载、GPU 负载、温度、内存）"""
    parts = []

    # CPU 负载
    cpu_load = get_cpu_load()
    if cpu_load is not None:
        parts.append(f"CPU 负载 {cpu_load:.2f}")

    # GPU/CPU 温度（hw-temp.log）
    hw = get_hw_status()
    if hw:
        parts.append(f"GPU {hw['gpu_busy']}%")
        parts.append(f"GPU 温度 {hw['gpu_temp']} 度")
        parts.append(f"CPU 温度 {hw['cpu_temp']} 度")

    # 内存
    mem_pct = get_system_memory()
    if mem_pct is not None:
        parts.append(f"内存 {mem_pct}%")

    if not parts:
        return None
    return "，".join(parts) + "。"


# ============ 语音时长估算 ============
def estimate_audio_duration(text):
    """根据文本估算语音时长（秒）。
    中文语速约 3-4 字/秒，英文约 15 词/秒。
    数字和特殊符号占用更多时间。
    """
    duration = 0.0
    for m in re.finditer(r'\d+\.?\d*', text):
        duration += len(m.group()) * 0.15
    no_num = re.sub(r'\d+\.?\d*', '', text)
    cn_count = sum(1 for ch in no_num if '\u4e00' <= ch <= '\u9fff')
    en_count = sum(1 for ch in no_num if ch.isascii() and ch.isalpha())
    other = len(no_num) - cn_count - en_count
    duration += cn_count * 0.30 + en_count * 0.04 + other * 0.08
    return max(duration, 0.5)

# ============ TTS 请求工具 ============
def _build_tts_payload(text):
    """构建 TTS 请求 payload，强制中文语言。
    ensure_ascii=False 关键：让中文字符以 UTF-8 字节直接发送，
    而不是转成 unicode 转义序列。
    """
    return json.dumps({
        "text": text,
        "speaker": TTS_SPEAKER,
        "language": "chinese",
        "seed": TTS_SEED,
    }, ensure_ascii=False).encode("utf-8")


# ============ TTS 队列 ============
class TTSQueue:
    """TTS 播报队列，单线程发送。"""

    def __init__(self):
        self._queue = deque()
        self._lock = threading.Lock()
        self._worker = None
        self._sent_count = 0
        self._fail_count = 0

    def start(self):
        self._worker = threading.Thread(target=self._run, daemon=True, name="tts-worker")
        self._worker.start()

    def put(self, text, priority=0, tag=""):
        """入队。队列满时直接丢弃，不入队。"""
        with self._lock:
            if len(self._queue) >= TTS_QUEUE_MAX:
                logging.info(f'[Queue] 丢弃: "{text[:40]}" (队列已满 {TTS_QUEUE_MAX} 条)')
                return
            if priority >= 3:
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
        logging.info(f'[Queue] +"{text[:40]}" (pri={priority}, qsize={qsize})')

    def _run(self):
        while not _stop_event.is_set():
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
        """TTS 合成 + 播放。默认非流式，可通过 TTS_USE_STREAM 切换。"""
        if TTS_USE_STREAM:
            self._speak_prebuffer(text)
        else:
            self._speak_wav(text)

    def _speak_wav(self, text):
        """非流式 TTS：完整生成 WAV 再播放。优先稳定性。

        流程：
        1. POST /v1/tts（非流式），等待完整 WAV 数据返回
        2. 写入临时文件
        3. aplay -D default 播放
        4. 清理临时文件
        """
        est_duration = estimate_audio_duration(text)
        logging.info(f"[TTS] 非流式: \"{text[:50]}\" (估时 {est_duration:.1f}s)")

        payload = _build_tts_payload(text)
        t0 = time.time()
        wav_path = None
        conn = None

        try:
            # 请求 TTS，超时设为估算时长的 5 倍 + 30s 兜底
            tts_timeout = max(int(est_duration * 5) + 30, HTTP_TIMEOUT)
            conn = http.client.HTTPConnection("127.0.0.1", 12348, timeout=tts_timeout)
            conn.request("POST", "/v1/tts",
                         body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()

            if resp.status != 200:
                body = resp.read()
                logging.error(f"[TTS] HTTP {resp.status}: {body[:200]}")
                return

            # 读取完整 WAV 数据
            wav_data = resp.read()
            gen_time = time.time() - t0

            if not wav_data or len(wav_data) < 44:
                logging.error(f"[TTS] 返回数据过短: {len(wav_data)} bytes")
                return

            # 写入临时文件
            wav_path = f"/tmp/tts_{os.getpid()}_{int(time.time())}.wav"
            with open(wav_path, "wb") as f:
                f.write(wav_data)

            wav_size = len(wav_data)
            logging.info(f"[TTS] 生成完成: {wav_size} bytes, 耗时 {gen_time:.1f}s")

            # 播放
            aplay = subprocess.Popen(
                ["aplay", "-q", "-D", "default", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = aplay.communicate(timeout=est_duration * 3 + 30)

            if aplay.returncode != 0 and stderr:
                logging.warning(f"[Play] aplay 返回码 {aplay.returncode}: {stderr.decode()[:200]}")

            elapsed = time.time() - t0
            logging.info(f"[TTS] 播放完成: \"{text[:50]}\" ({elapsed:.1f}s total)")

        except Exception as e:
            logging.error(f"[TTS] 非流式异常: {e}", exc_info=True)
            self._fail_count += 1
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

    def _speak_prebuffer(self, text):
        """流式预缓冲 TTS：先估算时长，预填 80% 缓冲，再启动 aplay 边生成边播放。

        流程：
        1. 发起 TTS 流式请求 (raw PCM)
        2. 数据先积累到内存 prebuffer，达到 80% 时长目标
        3. 创建 FIFO，启动 aplay 从 FIFO 读取（O_RDONLY 阻塞直到有写入者）
        4. 后台线程：把 prebuffer 写入 FIFO，然后持续把 TTS 流式数据写入 FIFO
        5. TTS 完成后关闭 FIFO 写端，aplay 读完自动退出
        """
        est_duration = estimate_audio_duration(text)
        # 预缓冲目标：80% 时长，最少 2 秒（应对 RTF 高的情况）
        prebuffer_sec = max(est_duration * 0.8, 2.0)
        prebuffer_bytes = int(prebuffer_sec * TTS_BYTES_PER_SEC)
        # 限制范围：32KB ~ 1MB
        prebuffer_bytes = max(32 * 1024, min(1024 * 1024, prebuffer_bytes))

        logging.info(f"[TTS] 流式: \"{text[:50]}\" (估时 {est_duration:.1f}s, 预缓冲 {prebuffer_sec:.1f}s / {prebuffer_bytes} bytes)")

        payload = _build_tts_payload(text)
        t0 = time.time()
        fifo_path = None
        conn = None
        writer_thread = None
        aplay = None

        try:
            conn = http.client.HTTPConnection("127.0.0.1", 12348, timeout=HTTP_TIMEOUT)
            conn.request("POST", "/v1/tts/stream",
                         body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()

            if resp.status != 200:
                body = resp.read()
                logging.error(f"[TTS] HTTP {resp.status}: {body[:200]}")
                conn.close()
                conn = None
                return

            # Phase 1: 预缓冲 - 积累数据到内存
            prebuffer = bytearray()
            while len(prebuffer) < prebuffer_bytes:
                chunk = resp.read(32768)
                if not chunk:
                    break
                prebuffer.extend(chunk)

            prebuffer_time = time.time() - t0
            prebuffer_audio_sec = len(prebuffer) / TTS_BYTES_PER_SEC
            logging.info(f"[Prebuf] 预缓冲完成: {len(prebuffer)} bytes ({prebuffer_audio_sec:.2f}s audio), 耗时 {prebuffer_time:.1f}s")

            # Phase 2: 创建 FIFO + 启动 aplay + 写入数据
            fifo_path = f"/tmp/tts_fifo_{os.getpid()}_{time.time()}"
            os.mkfifo(fifo_path, 0o600)

            # writer 线程退出标志
            writer_stop = threading.Event()

            def _fifo_writer():
                """后台线程：写入 prebuffer + 持续流式数据到 FIFO。"""
                fd = -1
                try:
                    fd = os.open(fifo_path, os.O_WRONLY)
                    if prebuffer:
                        os.write(fd, bytes(prebuffer))
                    while not writer_stop.is_set():
                        chunk = resp.read(32768)
                        if not chunk:
                            break
                        os.write(fd, chunk)
                except BrokenPipeError:
                    pass
                except Exception as e:
                    logging.error(f"[Writer] 异常: {e}")
                finally:
                    if fd >= 0:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            writer_thread = threading.Thread(target=_fifo_writer, daemon=True)
            writer_thread.start()

            aplay = subprocess.Popen(
                ["aplay", "-q", "-D", "default",
                 "-r", str(TTS_SAMPLE_RATE),
                 "-f", "S16_LE",
                 "-t", "raw",
                 "-c", "1",
                 fifo_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            writer_thread.join(timeout=HTTP_TIMEOUT)
            if writer_thread.is_alive():
                logging.warning("[Writer] 线程超时，强制停止")
                writer_stop.set()
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

            try:
                aplay.wait(timeout=est_duration * 2 + 10)
            except subprocess.TimeoutExpired:
                logging.warning("[Play] aplay 超时，强制终止")
                aplay.kill()
                aplay.wait()

            elapsed = time.time() - t0
            total = len(prebuffer)
            logging.info(f"[TTS] 流式 OK: \"{text[:50]}\" ({total} bytes prebuffer, {elapsed:.1f}s total)")

        except Exception as e:
            logging.error(f"[TTS] 流式异常: {e}", exc_info=True)
            self._fail_count += 1
            # 流式失败，无 fallback，直接放弃本次播报
        finally:
            # 清理顺序：先停 writer，再 kill aplay，最后删 FIFO
            if writer_thread and writer_thread.is_alive():
                writer_stop.set()
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                writer_thread.join(timeout=5)
            if aplay and aplay.poll() is None:
                aplay.kill()
                aplay.wait()
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if fifo_path:
                try:
                    os.unlink(fifo_path)
                except OSError:
                    pass


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
        logging.error(f"[READ] {filepath}: {e}")
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

        m = MODEL_PROXY_RE.search(s)
        if m:
            model_name = m.group(1)
            port = m.group(2)
            if model_name != current_model or port != current_port:
                current_model = model_name
                current_port = port
                state["current_model"] = current_model
                state["current_port"] = current_port
                short = model_name.replace("Qwen3.6-", "").replace("-UD-Q8_K_XL", "")
                text = BroadcastTexts.pick("MODEL_SWITCH", model=short)
                if text:
                    broadcasts.append((text, 1, "model_switch"))
            continue

        m = TASK_LAUNCH_RE.search(s)
        if m:
            task_id = int(m.group(1))
            state["_active_task"] = task_id
            text = BroadcastTexts.pick("TASK_START", task_id=num_to_chinese(task_id))
            if text:
                broadcasts.append((text, 1, "task_start"))
            continue

        m = TASK_PREFILL_RE.search(s)
        if m:
            task_id = int(m.group(1))
            ms = float(m.group(2))
            tokens = int(m.group(3))
            speed = tokens / (ms / 1000) if ms > 0 else 0
            text = BroadcastTexts.pick("TASK_PREFILL",
                                       task_id=num_to_chinese(task_id), tokens=tokens, speed=f"{speed:.0f}")
            if text:
                broadcasts.append((text, 1, "task_prefill"))
            continue

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
                                           task_id=num_to_chinese(task_id), decoded=decoded, speed=f"{tg:.1f}")
                if text:
                    broadcasts.append((text, 0, "task_gen"))
            continue

        m = TASK_RELEASE_RE.search(s)
        if m:
            task_id = int(m.group(1))
            n_tokens = int(m.group(2))
            state["_active_task"] = None
            state["_last_gen_milestone"] = 0
            text = BroadcastTexts.pick("TASK_DONE", task_id=num_to_chinese(task_id), tokens=n_tokens)
            if text:
                broadcasts.append((text, 1, "task_done"))
            continue

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


# ============ hw-temp.log 分析 ============
def parse_hw_temp_line(line):
    m = HW_TEMP_LOG_RE.search(line)
    if not m:
        return None
    return {
        "timestamp": m.group(1),
        "gpu_busy": int(m.group(2)),
        "gpu_temp": int(m.group(3)),
        "cpu_temp": int(m.group(4)),
        "nvme_temp": int(m.group(5)),
        "r8169_temp": int(m.group(6)),
        "eno1_temp": int(m.group(7)),
        "wifi_temp": int(m.group(8)),
    }


def analyze_hw_temp_lines(lines):
    """分析 hw-temp.log 增量行，返回硬件告警列表"""
    alerts = []
    for line in lines:
        data = parse_hw_temp_line(line)
        if not data:
            continue
        line_alerts = []
        # GPU 温度
        t = data["gpu_temp"]
        if t >= GPU_TEMP_CRIT:
            line_alerts.append({"type": "hw_gpu_temp_crit", "severity": 3, "temp": t})
        elif t >= GPU_TEMP_WARN:
            line_alerts.append({"type": "hw_gpu_temp_warn", "severity": 1, "temp": t})
        # CPU 温度
        ct = data["cpu_temp"]
        if ct >= CPU_TEMP_CRIT:
            line_alerts.append({"type": "hw_cpu_temp_crit", "severity": 3, "temp": ct})
        elif ct >= CPU_TEMP_WARN:
            line_alerts.append({"type": "hw_cpu_temp_warn", "severity": 1, "temp": ct})
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
            return s
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "file_offsets": {},
        "last_broadcast_time": 0,
        "last_broadcast_type": "",
        "last_daily_report_time": 0,
        "total_launched": 0,
        "completed_tasks": 0,
        "alert_cooldown": {},
        "current_model": "",
        "current_port": "",
    }


def save_state(state):
    """原子写入 state.json：先写临时文件，再 rename 替换。"""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in state.items() if not k.startswith("_")}
        tmp_path = str(STATE_FILE) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, STATE_FILE)
    except IOError as e:
        logging.error(f"[STATE] 保存失败: {e}")


# ============ 慢速轮询播报决策 ============
def decide_slow_broadcast(alerts, state):
    """慢速轮询的告警决策，返回 (text, tag, priority) 或 None"""
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
                "hw_cpu_temp_crit": ("HW_CPU_TEMP_CRIT", {"temp": alert.get("temp", "?")}),
                "hw_mem_crit": ("HW_MEM_CRIT", {"pct": f"{alert.get('pct', 0):.0f}"}),
            }
            category, kwargs = text_map.get(atype, ("CRITICAL", {}))
            text = BroadcastTexts.pick(category, **kwargs)
            if text:
                state["alert_cooldown"][atype] = now
                return text, atype, 3

    if not cooldown_ok:
        return None, "", 0

    # P2: 一般错误
    errors = [a for a in alerts if a["severity"] == 2]
    if errors:
        return BroadcastTexts.pick("ERROR"), "error", 1

    # P3: 硬件警告
    hw_warns = [a for a in alerts if a["severity"] == 1 and a["type"].startswith("hw_")]
    if hw_warns:
        alert = hw_warns[0]
        atype = alert["type"]
        hw_map = {
            "hw_gpu_temp_warn": ("HW_GPU_TEMP_WARN", {"temp": alert.get("temp", "?")}),
            "hw_cpu_temp_warn": ("HW_CPU_TEMP_WARN", {"temp": alert.get("temp", "?")}),
            "hw_mem_warn": ("HW_MEM_WARN", {"pct": f"{alert.get('pct', 0):.0f}"}),
        }
        category, kwargs = hw_map.get(atype, ("HW_MEM_WARN", {}))
        text = BroadcastTexts.pick(category, **kwargs)
        if text:
            return text, atype, 1

    # P4: 日常播报（独立计时，不依赖 last_broadcast_time）
    if (now - state.get("last_daily_report_time", 0)) >= DAILY_INTERVAL:
        active = state.get("_active_task") is not None
        status_text = BroadcastTexts.pick("BUSY" if active else "QUIET")
        daily_report = build_daily_report()
        if status_text:
            if daily_report:
                return f"{status_text} {daily_report}", "daily", 0
            return status_text, "daily", 0

    return None, "", 0


# ============ 主循环 ============
def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    setup_logging()

    logging.info(f"[Monitor] 启动监控播报系统 v8 (hw-temp.log 综合硬件监控)")
    logging.info(f"[Monitor] 高频轮询: {FAST_POLL}s (模型+任务) | 低频轮询: {SLOW_POLL}s (硬件+告警)")
    logging.info(f"[Monitor] TTS: {TTS_URL}")
    logging.info(f"[Monitor] speaker={TTS_SPEAKER} seed={TTS_SEED} language=chinese")
    logging.info(f"[Monitor] 队列最大: {TTS_QUEUE_MAX} 条，超出直接丢弃")
    logging.info(f"[Monitor] HTTP 超时: {HTTP_TIMEOUT}s")
    logging.info(f"[Monitor] 日志: {ROUTER_LOG}")
    logging.info(f"[Monitor] 硬件: {HW_TEMP_LOG}")
    logging.info(f"[Monitor] 自身日志: {MONITOR_LOG_FILE} (5MB x3 轮转)")

    state = load_state()
    offsets = state.get("file_offsets", {})

    # 迁移：如果旧 gpu-temp.log offset 存在，清除它
    old_gpu_key = str(LOG_DIR / "gpu-temp.log")
    if old_gpu_key in offsets:
        del offsets[old_gpu_key]
        logging.info(f"[Monitor] 清除旧 gpu-temp.log offset")

    for fpath in [ROUTER_LOG, HW_TEMP_LOG]:
        fp = str(fpath)
        if fp not in offsets:
            try:
                offsets[fp] = fpath.stat().st_size
                logging.info(f"[Monitor] {fpath.name}: 从末尾开始 (offset={offsets[fp]})")
            except FileNotFoundError:
                offsets[fp] = 0
                logging.info(f"[Monitor] {fpath.name}: 不存在")
    state["file_offsets"] = offsets

    state["_active_task"] = None
    state["_last_gen_milestone"] = 0

    tts = TTSQueue()
    tts.start()

    fast_counter = 0

    while not _stop_event.is_set():
        try:
            # 快速轮询：router.log（模型+任务）
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
                    logging.info(f"[Fast] {ROUTER_LOG.name}: {len(fast_broadcasts)} 播报")

            # 慢速轮询
            if fast_counter >= SLOW_POLL // FAST_POLL:
                fast_counter = 0

                all_alerts = []

                # 慢速轮询复用快速轮询的 offset（不再维护独立 slow offset）
                # 读取快速轮询之后的增量日志，仅做告警分析
                slow_offset = state["file_offsets"].get(fp, 0)
                slow_lines, slow_new_offset = read_new_lines(ROUTER_LOG, slow_offset)
                if slow_lines:
                    state["file_offsets"][fp] = slow_new_offset
                    alerts = analyze_router_slow(slow_lines)
                    all_alerts.extend(alerts)
                    if alerts:
                        logging.info(f"[Slow] {ROUTER_LOG.name}: {len(alerts)} 告警")

                # 硬件温度告警
                fp_hw = str(HW_TEMP_LOG)
                offset_hw = state["file_offsets"].get(fp_hw, 0)
                hw_lines, hw_new_offset = read_new_lines(HW_TEMP_LOG, offset_hw)
                if hw_lines:
                    state["file_offsets"][fp_hw] = hw_new_offset
                    hw_alerts = analyze_hw_temp_lines(hw_lines)
                    all_alerts.extend(hw_alerts)
                    if hw_alerts:
                        logging.info(f"[Slow] {HW_TEMP_LOG.name}: {len(hw_alerts)} 告警")

                # 系统内存告警
                mem_pct = get_system_memory()
                if mem_pct is not None:
                    if mem_pct >= MEM_CRIT_PCT:
                        all_alerts.append({"type": "hw_mem_crit", "severity": 3, "pct": mem_pct})
                    elif mem_pct >= MEM_WARN_PCT:
                        all_alerts.append({"type": "hw_mem_warn", "severity": 1, "pct": mem_pct})

                result = decide_slow_broadcast(all_alerts, state)
                if result and result[0]:
                    text, btype, pri = result
                    tts.put(text, priority=pri, tag=btype)
                    state["last_broadcast_time"] = time.time()
                    state["last_broadcast_type"] = btype
                    if btype == "daily":
                        state["last_daily_report_time"] = time.time()

            save_state(state)
            fast_counter += 1

        except Exception as e:
            logging.error(f"[Error] {e}", exc_info=True)

        if not _stop_event.is_set():
            for _ in range(FAST_POLL):
                if _stop_event.is_set():
                    break
                time.sleep(1)

    save_state(state)
    logging.info("[Monitor] 已退出")


if __name__ == "__main__":
    main()
