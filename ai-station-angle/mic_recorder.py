#!/usr/bin/env python3
"""
语音助手 - 麦克风录音模块

ALSA 配置（/etc/asound.conf）：
  pcm.!default        = dmix   → hw:1,0 (ALC245 播放共享, 44100/S16_LE/2ch)
  pcm.default_capture = dsnoop  → hw:1,0 (ALC245 录音共享, 44100/S16_LE/2ch)

录音输出 44100/2ch/S16_LE WAV，不做降采样/混缩。
VAD 用左声道 RMS 做能量检测。
"""

import argparse
import math
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path

# ============ 录音参数 ============
RECORD_DEVICE = "default_capture"
RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2  # S16_LE

# ============ VAD 参数 ============
FRAME_MS = 30
FRAME_SAMPLES = int(RATE * FRAME_MS / 1000)   # 1323 samples/frame
FRAME_BYTES = FRAME_SAMPLES * CHANNELS * SAMPLE_WIDTH  # 5292 bytes

SILENCE_THRESHOLD = 1000  # RMS 能量阈值
SILENCE_DURATION = 1.5
PRE_SPEECH_BUFFER = 0.3
MAX_RECORD_SECONDS = 30
MIN_SPEECH_SECONDS = 0.3
LISTEN_TIMEOUT = 60
WARMUP_FRAMES = 10        # 跳过启动前 N 帧（arecord 填充噪声）

OUTPUT_DIR = Path(tempfile.gettempdir()) / "voice_assistant"


def compute_rms(data: bytes) -> float:
    """计算 S16_LE 2ch 数据左声道的 RMS 能量。"""
    count = len(data) // (SAMPLE_WIDTH * CHANNELS)
    if count == 0:
        return 0.0
    total = 0
    for i in range(count):
        offset = i * SAMPLE_WIDTH * CHANNELS
        sample = struct.unpack_from('<h', data, offset)[0]
        total += sample * sample
    return math.sqrt(total / count)


def save_wav(path: Path, pcm_data: bytes):
    """保存 S16_LE/44100/2ch PCM 数据为 WAV 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(RATE)
        wf.writeframes(pcm_data)


class MicRecorder:
    def __init__(self,
                 device: str = RECORD_DEVICE,
                 silence_threshold: int = SILENCE_THRESHOLD,
                 silence_duration: float = SILENCE_DURATION,
                 max_record: float = MAX_RECORD_SECONDS,
                 min_speech: float = MIN_SPEECH_SECONDS,
                 listen_timeout: float = LISTEN_TIMEOUT):
        self.device = device
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.max_record = max_record
        self.min_speech = min_speech
        self.listen_timeout = listen_timeout
        self._proc = None

    def _start_arecord(self) -> subprocess.Popen:
        """启动常驻 arecord 进程，输出 raw S16_LE/44100/2ch PCM。"""
        proc = subprocess.Popen(
            ["arecord", "-D", self.device,
             "-r", str(RATE),
             "-f", "S16_LE",
             "-c", str(CHANNELS),
             "-t", "raw"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._proc = proc
        return proc

    def _stop_arecord(self):
        if self._proc:
            self._proc.kill()
            self._proc.wait()
            self._proc = None

    def _read_frame(self, proc) -> bytes | None:
        """读取一帧 PCM 数据。"""
        chunk = proc.stdout.read(FRAME_BYTES)
        if not chunk or len(chunk) < FRAME_BYTES:
            return None
        return chunk

    def _warmup(self, proc):
        """跳过启动填充噪声。"""
        for _ in range(WARMUP_FRAMES):
            self._read_frame(proc)

    def calibrate(self, duration: float = 2.0) -> int:
        """校准：录 N 秒环境噪声，返回建议阈值。"""
        print(f"[VAD] 校准中，请保持安静 {duration}s...")
        proc = self._start_arecord()
        rms_values = []
        target = int(duration * 1000 / FRAME_MS)
        try:
            self._warmup(proc)
            for _ in range(target):
                chunk = self._read_frame(proc)
                if chunk is None:
                    break
                rms_values.append(compute_rms(chunk))
        finally:
            self._stop_arecord()

        if not rms_values:
            return SILENCE_THRESHOLD
        avg = sum(rms_values) / len(rms_values)
        mx = max(rms_values)
        suggested = max(int(avg * 3), 200)
        print(f"[VAD] 噪声: avg={avg:.0f} max={mx:.0f} → 建议阈值: {suggested}")
        return suggested

    def record_once(self, proc=None) -> Path | None:
        """录音一次。proc 已有则复用（常驻模式），否则临时启动。"""
        own_proc = proc is None
        if own_proc:
            proc = self._start_arecord()
            self._warmup(proc)

        print(f"[Mic] 监听中 (threshold={self.silence_threshold})...")

        pre_buffer = []
        pre_buffer_size = int(PRE_SPEECH_BUFFER * 1000 / FRAME_MS)
        frames = []
        is_speaking = False
        silence_frames = 0
        silence_limit = int(self.silence_duration * 1000 / FRAME_MS)
        max_frames = int(self.max_record * 1000 / FRAME_MS)
        start_time = time.time()

        try:
            while True:
                if not is_speaking and self.listen_timeout > 0:
                    if time.time() - start_time > self.listen_timeout:
                        print("[Mic] 监听超时，未检测到语音")
                        return None

                chunk = self._read_frame(proc)
                if chunk is None:
                    break

                rms = compute_rms(chunk)

                if not is_speaking:
                    pre_buffer.append(chunk)
                    if len(pre_buffer) > pre_buffer_size:
                        pre_buffer.pop(0)
                    if rms > self.silence_threshold:
                        is_speaking = True
                        frames.extend(pre_buffer)
                        frames.append(chunk)
                        print(f"[VAD] 语音开始 (rms={rms:.0f})")
                        silence_frames = 0
                else:
                    frames.append(chunk)
                    if rms < self.silence_threshold:
                        silence_frames += 1
                        if silence_frames >= silence_limit:
                            print(f"[VAD] 语音结束 ({len(frames)} frames)")
                            break
                    else:
                        silence_frames = 0

                    if len(frames) >= max_frames:
                        print(f"[VAD] 达到最大时长 {self.max_record}s")
                        break

            if not is_speaking:
                return None

            raw_pcm = b''.join(frames)
            total_samples = len(raw_pcm) // (SAMPLE_WIDTH * CHANNELS)
            duration = total_samples / RATE
            if duration < self.min_speech:
                print(f"[Mic] 太短 ({duration:.1f}s)，丢弃")
                return None

            wav_path = OUTPUT_DIR / f"rec_{int(time.time())}.wav"
            save_wav(wav_path, raw_pcm)
            print(f"[Mic] 保存: {wav_path} ({duration:.1f}s, {CHANNELS}ch/{RATE}Hz)")
            return wav_path
        finally:
            if own_proc:
                self._stop_arecord()

    def listen_loop(self, callback):
        """常驻监听：arecord 进程持续运行，循环检测语音。"""
        proc = self._start_arecord()
        self._warmup(proc)
        print(f"[Mic] 常驻监听启动 (device={self.device})")
        try:
            while True:
                wav_path = self.record_once(proc)
                if wav_path is not None:
                    if callback(wav_path) is False:
                        break
        except KeyboardInterrupt:
            print("\n[Mic] 停止监听")
        finally:
            self._stop_arecord()
            print("[Mic] 常驻监听已停止")


def main():
    parser = argparse.ArgumentParser(description="麦克风录音模块")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--device", default=RECORD_DEVICE)
    parser.add_argument("--threshold", type=int, default=SILENCE_THRESHOLD)
    args = parser.parse_args()

    recorder = MicRecorder(device=args.device, silence_threshold=args.threshold)

    if args.calibrate:
        threshold = recorder.calibrate()
        print(f"\n建议: SILENCE_THRESHOLD = {threshold}")
    elif args.record:
        wav_path = recorder.record_once()
        if wav_path:
            print(f"\nWAV: {wav_path}")
        else:
            print("\n未录到有效语音")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
