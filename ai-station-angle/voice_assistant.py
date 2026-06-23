#!/usr/bin/env python3
"""
AI 台灯语音助手 - 主程序

链路: 麦克风 → VAD → ASR → LLM → TTS → 扬声器

用法:
  python3 voice_assistant.py                # 启动语音助手
  python3 voice_assistant.py --test-mic     # 仅测试麦克风录音
  python3 voice_assistant.py --test-asr     # 测试 ASR（录音→识别）
  python3 voice_assistant.py --test-llm     # 测试 LLM（录音→识别→对话）
  python3 voice_assistant.py --calibrate    # 校准麦克风
"""

import argparse
import sys
import time

from mic_recorder import MicRecorder
from asr_module import transcribe
from llm_module import chat
from tts_module import speak, synthesize, play_wav


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


def run_full_loop():
    """完整语音助手循环：麦克风 → ASR → LLM → TTS → 播放。"""
    recorder = MicRecorder()
    history = []
    print("=" * 50)
    print("  AI 台灯语音助手")
    print("  说句话开始对话，Ctrl+C 退出")
    print("=" * 50)

    try:
        while True:
            # 1. 录音
            wav = recorder.record_once()
            if not wav:
                continue

            # 2. ASR
            user_text = transcribe(wav)
            if not user_text:
                print("[助手] 没听清，请再说一遍")
                speak("没听清，请再说一遍")
                continue

            print(f"\n你: {user_text}")

            # 3. LLM
            reply = chat(user_text, history=history if len(history) < 10 else history[-10:])
            if not reply:
                print("[助手] 思考失败")
                speak("我思考了一下，但出了点问题")
                continue

            print(f"助手: {reply}")

            # 4. TTS + 播放
            speak(reply)

            # 5. 更新历史
            history.append({"role": "user", "content": user_text})
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
    else:
        run_full_loop()


if __name__ == "__main__":
    main()
