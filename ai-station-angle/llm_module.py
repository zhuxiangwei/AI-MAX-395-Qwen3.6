#!/usr/bin/env python3
"""
语音助手 - LLM 对话模块

调用 Router (端口 12345) 管理的 358 模型（Qwen3.6-35B-A3B-UD-Q8_K_XL）。
Router 双模型模式 (models-max=2)，358 通过 router-preset.ini 配置。
sleep-idle-seconds=600，空闲后自动卸载，需 prewarm 唤醒。

端点: POST http://127.0.0.1:12345/v1/chat/completions
"""

import json
import threading
import http.client
from openai import OpenAI
from tools import TOOLS, execute_tool_calls

# Router 统一入口
ROUTER_HOST = "127.0.0.1"
ROUTER_PORT = 12345
ROUTER_API_KEY = "71769f2CeCE681015e1B71eCf848900e"

# 358 模型（由 Router 管理，alias=358）
LLM_MODEL = "358"
MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """你是一个简洁的语音助手。回答要求：
1. 口语化，简短直接，通常不超过两三句话
2. 不要使用 markdown、表格、代码块等格式
3. 不要说"作为AI"之类的套话
4. 像和朋友聊天一样自然
5. 如果工具返回了数据，基于数据给出自然简洁的回答，不要复述原始数据格式"""


_client = OpenAI(
    base_url=f"http://{ROUTER_HOST}:{ROUTER_PORT}/v1",
    api_key=ROUTER_API_KEY,
    timeout=300,
)

# Pre-warm 状态
_prewarm_thread = None
_prewarm_done = False


def prewarm():
    """后台预热 358 模型（唤醒词触发后立即调用）。

    通过 POST /models/load 触发 Router 加载 358 模型。
    不做任何推理，不污染 KV cache。
    如果 358 已加载，立即返回。
    """
    global _prewarm_done, _prewarm_thread
    _prewarm_done = False

    def _do_prewarm():
        global _prewarm_done
        try:
            conn = http.client.HTTPConnection(ROUTER_HOST, ROUTER_PORT, timeout=5)
            # 检查 358 当前状态
            conn.request("GET", "/v1/models", headers={"Authorization": f"Bearer {ROUTER_API_KEY}"})
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            conn.close()

            # 找 358 的状态
            status = None
            for m in data.get("data", []):
                if "35B-A3B" in m.get("id", "") or "358" in m.get("id", "") or "358" in str(m.get("aliases", [])):
                    status = m["status"]["value"]
                    break

            if status == "loaded":
                print("[LLM] 358 已就绪")
                _prewarm_done = True
                return

            # 触发加载
            print(f"[LLM] 358 状态={status}，触发 /models/load...")
            conn = http.client.HTTPConnection(ROUTER_HOST, ROUTER_PORT, timeout=10)
            conn.request(
                "POST", "/models/load",
                body=json.dumps({"model": "Qwen3.6-35B-A3B-UD-Q8_K_XL"}),
                headers={
                    "Authorization": f"Bearer {ROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp = conn.getresponse()
            result = json.loads(resp.read().decode())
            conn.close()
            print(f"[LLM] /models/load 响应: {result}")

            # 等待加载完成
            for i in range(60):
                import time
                time.sleep(2)
                conn = http.client.HTTPConnection(ROUTER_HOST, ROUTER_PORT, timeout=5)
                conn.request("GET", "/v1/models", headers={"Authorization": f"Bearer {ROUTER_API_KEY}"})
                resp = conn.getresponse()
                data = json.loads(resp.read().decode())
                conn.close()
                for m in data.get("data", []):
                    if "35B-A3B" in m.get("id", ""):
                        status = m["status"]["value"]
                        if status == "loaded":
                            print("[LLM] 358 加载完成")
                            _prewarm_done = True
                            return
                        break
            print("[LLM] 358 加载超时")
            _prewarm_done = True
        except Exception as e:
            print(f"[LLM] 预热失败: {e}")
            _prewarm_done = True

    _prewarm_thread = threading.Thread(target=_do_prewarm, daemon=True)
    _prewarm_thread.start()


def chat(user_text: str, history: list | None = None) -> str | None:
    """发送文本到 LLM，支持 tool calling，返回回复文本。"""
    # 如果 prewarm 线程还在跑，等它完成
    if _prewarm_thread and not _prewarm_done:
        print("[LLM] 等待 358 唤醒完成...")
        _prewarm_thread.join(timeout=120)

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

        if finish_reason == "tool_calls" and hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_round += 1
            print(f"[LLM] 第 {tool_round} 轮 tool calls ({len(msg.tool_calls)} 个)")

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            tool_calls_list = [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
            tool_responses = execute_tool_calls(tool_calls_list)
            for tr in tool_responses:
                messages.append(tr)
            continue

        text = msg.content or ""
        if text.strip():
            print(f"[LLM] 回复: {text}")
            return text.strip()
        else:
            print(f"[LLM] 空回复 (finish_reason={finish_reason})")
            return None

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
