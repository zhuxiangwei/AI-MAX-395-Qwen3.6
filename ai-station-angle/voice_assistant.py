#!/usr/bin/env python3
"""
AI 台灯语音助手 - 主程序

链路: 麦克风 → VAD → ASR → 唤醒词检测 → LLM → TTS → 扬声器

唤醒词模式:
  - 每段语音先过 ASR 识别
  - 检查文本是否包含唤醒词 ("你好小智" / "小智你好")
  - 命中 → 播放唤醒回复 → 继续听指令 → LLM → TTS
  - 未命中 → 丢弃，继续监听

用法:
  python3 voice_assistant.py                # 启动语音助手
  python3 voice_assistant.py --test-mic     # 仅测试麦克风录音
  python3 voice_assistant.py --test-asr     # 测试 ASR（录音→识别）
  python3 voice_assistant.py --test-llm     # 测试 LLM（录音→识别→对话）
  python3 voice_assistant.py --calibrate    # 校准麦克风
  python3 voice_assistant.py --test-wake    # 测试唤醒词检测
"""

import argparse
import re
import sys
import time

from pathlib import Path

from mic_recorder import MicRecorder
from asr_module import transcribe
from llm_module import chat
from tts_module import speak, synthesize, play_wav

# 唤醒回复缓存（预生成 WAV，避免每次合成）
WAKE_REPLY_PATH = Path(__file__).parent / "assets" / "wake_reply.wav"


# ============ 唤醒词配置 ============
# 唤醒词：ASR 识别文本中包含以下任意模式即触发
WAKE_PATTERNS = [
    r"你好[，,]?\s*小智",
    r"小智[，,]?\s*你好",
    r"你好小智",
    r"小智你好",
]
WAKE_REGEX = re.compile("|".join(WAKE_PATTERNS))

# 唤醒回复
WAKE_REPLY = "我是宇宙超级智多星，小智在此等候多时了！"

# 唤醒后等待指令的超时时间（秒）
COMMAND_TIMEOUT = 15


def check_wake_word(text: str) -> bool:
    """检查文本是否包含唤醒词。"""
    return bool(WAKE_REGEX.search(text))


def extract_command(text: str) -> str:
    """从识别文本中去掉唤醒词，提取后续指令。

    例:
      "你好小智今天天气怎么样" → "今天天气怎么样"
      "小智你好" → ""
    """
    cmd = WAKE_REGEX.sub("", text).strip()
    # 去掉可能残留的标点前缀
    cmd = re.sub(r'^[，,。\s]+', '', cmd)
    return cmd


def run_calibrate():
    """校准麦克风。"""
    recorder = MicRecorder()
    threshold = recorder.calibrate()
    print(f"\n建议 SILENCE_THRESHOLD = {threshold}")


def run_test_mic():
    """仅测试录音。"""
    recorder = MicRecorder()
    wav = recorder.record_once()
    if wav:
        print(f"\n录音文件: {wav}")
        print(f"播放: aplay -D default {wav}")
    else:
        print("\n未录到语音")


def run_test_asr():
    """测试录音 + ASR。"""
    recorder = MicRecorder()
    print("=== 录音 + ASR 测试 ===")
    wav = recorder.record_once()
    if not wav:
        print("未录到语音")
        return
    print(f"\n录音: {wav}")
    text = transcribe(wav)
    if text:
        print(f"\n识别结果: {text}")
    else:
        print("\n识别失败")


def run_test_llm():
    """测试录音 + ASR + LLM。"""
    recorder = MicRecorder()
    print("=== 录音 + ASR + LLM 测试 ===")
    wav = recorder.record_once()
    if not wav:
        print("未录到语音")
        return
    text = transcribe(wav)
    if not text:
        print("识别失败")
        return
    print(f"\n你: {text}")
    reply = chat(text)
    if reply:
        print(f"\n助手: {reply}")
    else:
        print("\nLLM 请求失败")


def run_test_wake():
    """测试唤醒词检测。"""
    recorder = MicRecorder()
    print("=== 唤醒词测试 ===")
    print(f"唤醒词: 你好小智 / 小智你好")
    print("说一句话试试...")
    wav = recorder.record_once()
    if not wav:
        print("未录到语音")
        return
    text = transcribe(wav)
    if not text:
        print("识别失败")
        return
    print(f"\n识别: {text}")
    if check_wake_word(text):
        cmd = extract_command(text)
        print(f"✅ 唤醒成功! 后续指令: '{cmd}'")
        speak(WAKE_REPLY)
        if cmd:
            reply = chat(cmd)
            if reply:
                print(f"助手: {reply}")
                speak(reply)
    else:
        print("❌ 未检测到唤醒词，忽略")


def run_full_loop():
    """完整语音助手循环（唤醒词模式）。

    流程:
      1. 持续监听，录到一段语音
      2. ASR 识别
      3. 检查是否含唤醒词
         - 否 → 丢弃，回到 1
         - 是 → 播放唤醒回复（阻塞，麦克风自然暂停）
      4. 提取唤醒词后的指令
         - 有指令 → 直接送 LLM
         - 无指令 → 再录一段作为指令
      5. LLM → TTS → 播放（阻塞）
      6. 回到 1

    TTS 播放使用同步阻塞 aplay，播放期间不会触发录音，避免回声。
    """
    recorder = MicRecorder()
    history = []

    print("=" * 50)
    print("  AI 台灯语音助手（唤醒词模式）")
    print(f"  唤醒词: 你好小智 / 小智你好")
    print("  Ctrl+C 退出")
    print("=" * 50)

    try:
        while True:
            # ── 1. 持续监听 ──
            wav = recorder.record_once()
            if not wav:
                continue

            # ── 2. ASR 识别 ──
            user_text = transcribe(wav)
            if not user_text:
                continue

            print(f"\n听到: {user_text}")

            # ── 3. 唤醒词检测 ──
            if not check_wake_word(user_text):
                # 不是在叫小智，忽略
                continue

            print("✅ 唤醒成功!")

            # ── 4. 播放唤醒回复（阻塞播放，期间不录音） ──
            if WAKE_REPLY_PATH.exists():
                play_wav(WAKE_REPLY_PATH)
            else:
                speak(WAKE_REPLY)

            # ── 5. 提取指令 ──
            command = extract_command(user_text)

            if not command:
                # 唤醒词后面没有指令，再录一段
                print(f"[助手] 请说指令（{COMMAND_TIMEOUT}s 内）...")
                recorder_cmd = MicRecorder(listen_timeout=COMMAND_TIMEOUT)
                cmd_wav = recorder_cmd.record_once()
                if not cmd_wav:
                    print("[助手] 超时，没有听到指令")
                    continue
                command = transcribe(cmd_wav)
                if not command:
                    print("[助手] 没听清指令")
                    speak("没听清，请再说一遍")
                    continue

            print(f"你: {command}")

            # ── 6. LLM → TTS → 播放（阻塞播放，期间不录音） ──
            reply = chat(command, history=history if len(history) < 10 else history[-10:])
            if not reply:
                print("[助手] 思考失败")
                speak("我思考了一下，但出了点问题")
                continue

            print(f"助手: {reply}")
            speak(reply)

            # ── 7. 更新历史 ──
            history.append({"role": "user", "content": command})
            history.append({"role": "assistant", "content": reply})

            print("\n" + "-" * 30)

    except KeyboardInterrupt:
        print("\n\n再见！")


def main():
    parser = argparse.ArgumentParser(description="AI 台灯语音助手")
    parser.add_argument("--calibrate", action="store_true", help="校准麦克风")
    parser.add_argument("--test-mic", action="store_true", help="测试录音")
    parser.add_argument("--test-asr", action="store_true", help="测试录音+ASR")
    parser.add_argument("--test-llm", action="store_true", help="测试录音+ASR+LLM")
    parser.add_argument("--test-wake", action="store_true", help="测试唤醒词检测")
    parser.add_argument("--threshold", type=int, default=1000, help="VAD 阈值")
    args = parser.parse_args()

    if args.calibrate:
        run_calibrate()
    elif args.test_mic:
        run_test_mic()
    elif args.test_asr:
        run_test_asr()
    elif args.test_llm:
        run_test_llm()
    elif args.test_wake:
        run_test_wake()
    else:
        run_full_loop()


if __name__ == "__main__":
    main()
