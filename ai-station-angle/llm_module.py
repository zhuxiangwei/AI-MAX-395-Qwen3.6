#!/usr/bin/env python3
"""
语音助手 - LLM 对话模块

调用本地 llama-server (Qwen3.6-35B-A3B 语音助手专用实例) 的 OpenAI 兼容 API。
支持 tool calling：LLM 可自主调用工具获取实时数据。

端点: POST http://127.0.0.1:12346/v1/chat/completions
注意: 12346 端口无需 API Key（仅本地访问）
"""

import json
from openai import OpenAI
from tools import TOOLS, execute_tool_calls

LLM_HOST = "127.0.0.1"
LLM_PORT = 12346  # 35B-A3B 语音助手专用实例（非 router 12345）
LLM_MODEL = "Qwen3.6-35B-A3B-UD-Q8_K_XL"
MAX_TOOL_ROUNDS = 5  # 防止 LLM 陷入 tool call 死循环

SYSTEM_PROMPT = """你是一个简洁的语音助手。回答要求：
1. 口语化，简短直接，通常不超过两三句话
2. 不要使用 markdown、表格、代码块等格式
3. 不要说"作为AI"之类的套话
4. 像和朋友聊天一样自然
5. 如果工具返回了数据，基于数据给出自然简洁的回答，不要复述原始数据格式"""


# OpenAI 兼容客户端（llama.cpp server 也支持这个协议）
# 12346 端口无需 API Key，传占位符即可
_client = OpenAI(
    base_url=f"http://{LLM_HOST}:{LLM_PORT}/v1",
    api_key="no-key",
    timeout=300,
)


def chat(user_text: str, history: list | None = None) -> str | None:
    """发送文本到 LLM，支持 tool calling，返回回复文本。

    流程：
      1. 发送用户消息 + tools 定义
      2. 如果 LLM 返回 tool_calls → 执行工具 → 回喂结果
      3. 重复直到 LLM 返回最终文本回复

    Args:
        user_text: 用户输入
        history: 对话历史 [{"role": "user/assistant", "content": "..."}]

    Returns:
        LLM 回复文本，失败返回 None
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    tool_round = 0
    while tool_round < MAX_TOOL_ROUNDS:
        try:
            response = _client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.6,
                top_p=0.95,
                max_tokens=1024,
                tools=TOOLS if TOOLS else None,
            )
        except Exception as e:
            print(f"[LLM] 请求失败: {e}")
            return None

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        msg = choice.message

        # ── LLM 要调用工具 ──
        if finish_reason == "tool_calls" and hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_round += 1
            print(f"[LLM] 第 {tool_round} 轮 tool calls ({len(msg.tool_calls)} 个)")

            # 把 assistant 的 tool_call 消息加入对话
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # 执行工具
            tool_calls_list = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
            tool_responses = execute_tool_calls(tool_calls_list)

            # 把工具结果加入对话
            for tr in tool_responses:
                messages.append(tr)

            # 继续下一轮，让 LLM 基于工具结果生成回答
            continue

        # ── LLM 返回了最终文本 ──
        text = msg.content or ""
        if text.strip():
            print(f"[LLM] 回复: {text}")
            return text.strip()
        else:
            # content 为空且不是 tool_calls，异常
            print(f"[LLM] 空回复 (finish_reason={finish_reason})")
            return None

    # 超过最大轮数
    print(f"[LLM] 警告：tool calling 超过 {MAX_TOOL_ROUNDS} 轮，强制终止")
    return "抱歉，我在处理你的请求时遇到了一些问题，请稍后再试。"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 llm_module.py <文本>")
        sys.exit(1)
    user_text = " ".join(sys.argv[1:])
    reply = chat(user_text)
    if reply:
        print(f"\n回复: {reply}")
    else:
        print("\n请求失败")
