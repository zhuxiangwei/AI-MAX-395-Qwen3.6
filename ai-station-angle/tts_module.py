#!/usr/bin/env python3
"""
语音助手 - TTS 语音合成模块

调用本地 Qwen3-TTS-12Hz-1.7B-CustomVoice 服务。
端点: POST http://127.0.0.1:9900/v1/tts
返回: WAV 音频数据 (S16_LE/24000Hz/1ch)
"""

import http.client
import json
import time
from pathlib import Path

TTS_HOST = "127.0.0.1"
TTS_PORT = 12348
TTS_SPEAKER = "vivian"   # 中文女声
TTS_LANGUAGE = "chinese"
TTS_SEED = 42
TIMEOUT = 120


def synthesize(text: str, output_path: str | Path | None = None) -> Path | None:
    """将文本合成为语音 WAV。

    Args:
        text: 要合成的文本
        output_path: 输出路径，None 则自动生成

    Returns:
        WAV 文件路径，失败返回 None
    """
    if not text or not text.strip():
        print("[TTS] 空文本，跳过")
        return None

    payload = json.dumps({
        "text": text,
        "speaker": TTS_SPEAKER,
        "language": TTS_LANGUAGE,
        "seed": TTS_SEED,
    }, ensure_ascii=False).encode("utf-8")

    est_duration = max(len(text) * 0.15, 3.0)
    tts_timeout = max(int(est_duration * 5) + 30, TIMEOUT)

    try:
        conn = http.client.HTTPConnection(TTS_HOST, TTS_PORT, timeout=tts_timeout)
        conn.request("POST", "/v1/tts", body=payload,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
    except Exception as e:
        print(f"[TTS] 请求失败: {e}")
        return None

    if resp.status != 200:
        print(f"[TTS] HTTP {resp.status}: {data[:200]}")
        return None

    if output_path is None:
        output_path = Path("/tmp/voice_assistant") / f"tts_{int(time.time())}.wav"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(data)

    print(f"[TTS] 合成: {len(data)} bytes → {output_path}")
    return output_path


def play_wav(wav_path: str | Path):
    """用 aplay 播放 WAV 文件（非阻塞，通过 systemd-run 脱离 session）。"""
    import subprocess
    wav_path = str(wav_path)
    try:
        subprocess.run(
            ["systemd-run", "--user", "--no-block",
             "aplay", "-q", "-D", "default", wav_path],
            check=True, capture_output=True, timeout=10
        )
        print(f"[TTS] 播放: {wav_path}")
    except subprocess.CalledProcessError as e:
        print(f"[TTS] 播放失败: {e.stderr.decode()}")
    except Exception as e:
        print(f"[TTS] 播放异常: {e}")


def speak(text: str):
    """一步合成并播放。"""
    wav_path = synthesize(text)
    if wav_path:
        play_wav(wav_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 tts_module.py <文本>")
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    speak(text)
