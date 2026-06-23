#!/usr/bin/env python3
"""
语音助手 - ASR 语音识别模块

调用本地 llama-server (Qwen3-ASR-1.7B) 的 OpenAI 兼容 API。
端点: POST http://127.0.0.1:48091/v1/audio/transcriptions
"""

import json
import re
import requests
from pathlib import Path

ASR_URL = "http://127.0.0.1:12347/v1/audio/transcriptions"
ASR_MODEL = "Qwen3-ASR-1.7B"
TIMEOUT = 60


def transcribe(wav_path: str | Path) -> str | None:
    """将 WAV 文件发送到 ASR 服务，返回识别文本。

    Args:
        wav_path: WAV 文件路径

    Returns:
        识别出的文本，失败返回 None
    """
    wav_path = Path(wav_path)
    if not wav_path.exists():
        print(f"[ASR] 文件不存在: {wav_path}")
        return None

    try:
        with open(wav_path, 'rb') as f:
            resp = requests.post(
                ASR_URL,
                files={'file': (wav_path.name, f, 'audio/wav')},
                data={'model': ASR_MODEL},
                timeout=TIMEOUT,
            )
    except requests.exceptions.RequestException as e:
        print(f"[ASR] 请求失败: {e}")
        return None

    if resp.status_code != 200:
        print(f"[ASR] HTTP {resp.status_code}: {resp.text}")
        return None

    data = resp.json()
    raw_text = data.get('text', '')

    # 解析格式: "language Chinese<asr_text>实际内容"（无闭合标签）
    match = re.search(r'<asr_text>(.*)', raw_text)
    if match:
        text = match.group(1).strip()
    else:
        # 兜底：去掉 language 前缀
        text = re.sub(r'^language\s+\w+\s*', '', raw_text).strip()

    print(f"[ASR] 识别: {text}")
    return text if text else None


def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 asr_module.py <wav_file>")
        sys.exit(1)

    wav_path = sys.argv[1]
    text = transcribe(wav_path)
    if text:
        print(f"\n识别结果: {text}")
    else:
        print("\n识别失败")


if __name__ == "__main__":
    main()
