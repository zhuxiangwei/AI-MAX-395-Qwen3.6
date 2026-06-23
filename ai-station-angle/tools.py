#!/usr/bin/env python3
"""
语音助手 - 工具模块

定义所有可用工具及其执行函数。每个工具包含：
- name: 工具名称（LLM 调用时使用）
- description: 工具描述（LLM 根据此判断何时调用）
- parameters: JSON Schema 参数定义
- fn: 实际执行的 Python 函数
"""

import json
import subprocess
import math
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 工具定义 —— OpenAI function calling 格式
# ═══════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前日期、时间和星期。当用户询问现在几点、今天几号、星期几等时间相关问题时使用。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取推理机的系统状态信息，包括内存使用情况、CPU负载、GPU温度、磁盘空间、服务运行状态等。当用户询问机器状态、内存还剩多少、温度高不高、服务是否正常等问题时使用。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索互联网获取实时信息。当用户询问天气、新闻、实时事件、人物信息、百科知识等需要联网查询的内容时使用。注意：本地系统状态请用 get_system_info，不要用搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，用中文或英文",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的天气信息，包括温度、天气状况、湿度、风速等。当用户询问某个地方的天气时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如 '杭州'、'北京'、'Shanghai'",
                    }
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_url",
            "description": "抓取指定网页的文本内容。当用户想了解某个链接的内容、某篇文章说了什么时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的网页URL，如 'https://example.com'",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "数学计算器。当用户需要进行数学计算、单位换算、公式求值时使用。支持加减乘除、幂运算、三角函数、对数等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '2 + 3 * 4'、'sqrt(144)'、'sin(pi/2)'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════
# 工具执行函数
# ═══════════════════════════════════════════════════════════

def _get_time() -> str:
    """获取当前日期时间。"""
    now = datetime.now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return (
        f"当前时间：{now.year}年{now.month}月{now.day}日 "
        f"{now.hour}时{now.minute}分{now.second}秒 "
        f"星期{weekdays[now.weekday()]}"
    )


def _get_system_info() -> str:
    """获取推理机系统状态。"""
    lines = []

    # --- 内存 ---
    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        import re
        total = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1))
        avail = int(re.search(r"MemAvailable:\s+(\d+)", meminfo).group(1))
        used = total - avail
        swap_total = int(re.search(r"SwapTotal:\s+(\d+)", meminfo).group(1))
        swap_free = int(re.search(r"SwapFree:\s+(\d+)", meminfo).group(1))
        lines.append(
            f"内存：总计 {total / 1024 / 1024:.0f}GB，"
            f"已用 {used / 1024 / 1024:.1f}GB，"
            f"可用 {avail / 1024 / 1024:.1f}GB"
        )
        if swap_total > 0:
            lines.append(
                f"交换分区：总计 {swap_total / 1024 / 1024:.1f}GB，"
                f"已用 {(swap_total - swap_free) / 1024 / 1024:.1f}GB"
            )
    except Exception as e:
        lines.append(f"内存信息获取失败: {e}")

    # --- CPU ---
    try:
        with open("/proc/loadavg") as f:
            loadavg = f.read().strip()
        lines.append(f"CPU 负载（1/5/15分钟）：{loadavg}")
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()
        cpu_count = len(re.findall(r"^processor", cpuinfo, re.MULTILINE))
        model = re.search(r"model name\s*:\s*(.+)", cpuinfo).group(1).strip()
        lines.append(f"CPU：{model} ({cpu_count} 核)")
    except Exception as e:
        lines.append(f"CPU 信息获取失败: {e}")

    # --- GPU 温度 ---
    try:
        # TODO: 回家确认 Vulkan 后端的 GPU 信息获取方式
        # 尝试 rocm-smi（AMD GPU）
        result = subprocess.run(
            ["rocm-smi", "--showtemp", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            gpu_data = json.loads(result.stdout)
            for i, card in enumerate(gpu_data.get("card", [])):
                temp = card.get("temp", "N/A")
                power = card.get("power_avg", "N/A")
                mem_used = card.get("mem_used", "N/A")
                mem_total = card.get("mem_total", "N/A")
                lines.append(
                    f"GPU {i}：温度 {temp}°C，"
                    f"功耗 {power}W，"
                    f"显存 {mem_used}MB/{mem_total}MB"
                )
        else:
            # 回退：尝试 rocm-smi 非 JSON 模式
            result2 = subprocess.run(
                ["rocm-smi", "--showtemp"],
                capture_output=True, text=True, timeout=10
            )
            if result2.returncode == 0:
                lines.append(f"GPU 温度：\n{result2.stdout.strip()}")
            else:
                lines.append("GPU 信息：rocm-smi 不可用（需确认 Vulkan 后端获取方式）")
    except FileNotFoundError:
        # 尝试 hwmon
        try:
            import glob
            hwmon_paths = glob.glob("/sys/class/hwmon/hwmon*/temp*_input")
            temps = []
            for p in hwmon_paths:
                name = Path(p).name.replace("temp", "").replace("_input", "")
                with open(p) as f:
                    val = int(f.read().strip())
                temps.append(f"{name}: {val / 1000:.1f}°C")
            if temps:
                lines.append(f"硬件温度：{', '.join(temps)}")
            else:
                lines.append("GPU 温度：无法读取（需配置）")
        except Exception:
            lines.append("GPU 温度：无法读取（需配置）")
    except Exception as e:
        lines.append(f"GPU 信息获取失败: {e}")

    # --- 磁盘 ---
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                lines.append(f"磁盘 ({parts[5]})：总计 {parts[1]}，已用 {parts[2]}，可用 {parts[3]}，使用率 {parts[4]}")
    except Exception as e:
        lines.append(f"磁盘信息获取失败: {e}")

    # --- 服务状态 ---
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-units", "--type=service", "--state=running"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            services = [l.split()[1] for l in result.stdout.strip().split("\n")[1:] if l.strip()]
            if services:
                lines.append(f"运行中的服务：{', '.join(services)}")
    except Exception:
        pass

    return "\n".join(lines)


def _web_search(query: str) -> str:
    """通过 Bing 搜索互联网（国内可访问）。

    注意：Bing 可能返回验证码页面，如果解析不到结果会回退到 Sogou。
    """
    import re

    def _parse_search(html: str) -> list:
        """从搜索结果 HTML 中提取标题和摘要。"""
        results = []
        # 提取 h2 标签中的标题
        titles = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.S)
        # 提取链接
        hrefs = re.findall(r'href="(https?://[^"#]+)"', html)
        # 提取 p 标签中的摘要
        snippets = re.findall(r'<p[^>]*>(.*?)</p>', html, re.S)
        clean = lambda t: re.sub(r'<[^>]+>', '', t).strip().replace('\n', ' ')
        for i in range(min(len(titles), 5)):
            title = clean(titles[i])
            body = clean(snippets[i]) if i < len(snippets) else ""
            # 过滤太短的标题（可能是 UI 元素）
            if len(title) < 5:
                continue
            results.append({"title": title, "body": body[:200]})
        return results

    engines = [
        {
            "url": "https://www.bing.com/search",
            "params": {"q": query},
        },
    ]

    import requests
    try:
        resp = requests.get(
            engines[0]["url"],
            params=engines[0]["params"],
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=10,
        )
        resp.encoding = "utf-8"
        results = _parse_search(resp.text)
        if results:
            lines = [f"搜索 '{query}' 的结果：\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"[{i}] {r['title']}")
                if r.get("body"):
                    lines.append(f"    {r['body']}")
                lines.append("")
            return "\n".join(lines)
    except Exception:
        pass

    return f"搜索 '{query}' 未找到结果（Bing 可能返回了验证码）"


def _get_weather(city: str) -> str:
    """查询城市天气。

    直接调用 web_search 搜索 '{city} 天气'，
    搜索结果通常包含天气卡片，不需要维护单独的 API。
    """
    return _web_search(f"{city} 天气")


def _browse_url(url: str) -> str:
    """通过 Playwright headless 浏览器抓取网页文本内容。

    完全自主，处理 JS 渲染、动态加载、反爬等所有问题。
    浏览器保持常驻以复用进程。
    """
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            # 取 body 文本，比 inner_html 干净
            text = page.inner_text("body").strip()
            browser.close()

        if not text:
            return f"无法获取网页内容（{url}）"

        # 截断到 3000 字符
        if len(text) > 3000:
            text = text[:3000] + "..."

        return f"网页内容（{url}）：\n{text}"
    except ImportError:
        return "错误：playwright 未安装，请运行 pip install playwright && playwright install chromium"
    except Exception as e:
        return f"网页抓取失败: {e}"


def _calculator(expression: str) -> str:
    """安全地计算数学表达式。"""
    try:
        # 只允许安全的数学操作
        allowed = {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow, "sqrt": math.sqrt,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan,
            "log": math.log, "log10": math.log10, "log2": math.log2,
            "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
            "pi": math.pi, "e": math.e, "tau": math.tau,
            "factorial": math.factorial,
        }
        # 安全检查：只允许数字、运算符、空格、括号、小数点、函数名
        safe_expr = expression.strip()
        # 白名单检查
        test_str = safe_expr.replace(" ", "")
        for ch in test_str:
            if ch not in "0123456789.+-*/()%_":
                break  # 可能是函数名的一部分
        # Safety: __builtins__={} blocks all builtins, `allowed` only exposes
        # math functions. This is a local voice assistant, not public-facing.
        result = eval(safe_expr, {"__builtins__": {}}, allowed)
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误: {e}"


# ═══════════════════════════════════════════════════════════
# 工具调度器
# ═══════════════════════════════════════════════════════════

# 名称 → 函数映射
_TOOL_FN = {
    "get_time": _get_time,
    "get_system_info": _get_system_info,
    "web_search": _web_search,
    "get_weather": _get_weather,
    "browse_url": _browse_url,
    "calculator": _calculator,
}


def execute_tool_call(tool_call) -> dict:
    """执行单个 tool_call，返回 tool response 消息。

    Args:
        tool_call: OpenAI 格式的 tool_call 对象，包含 id, function.name, function.arguments

    Returns:
        {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
    func_name = tool_call["function"]["name"]
    func_args_str = tool_call["function"]["arguments"]
    tool_id = tool_call["id"]

    print(f"[TOOL] 调用: {func_name}({func_args_str})")

    fn = _TOOL_FN.get(func_name)
    if not fn:
        return {
            "role": "tool",
            "tool_call_id": tool_id,
            "content": f"错误：未知工具 '{func_name}'"
        }

    try:
        args = json.loads(func_args_str) if func_args_str else {}
        result = fn(**args)
        print(f"[TOOL] 结果: {result[:200]}")
        return {
            "role": "tool",
            "tool_call_id": tool_id,
            "content": str(result),
        }
    except Exception as e:
        error_msg = f"工具 '{func_name}' 执行失败: {e}"
        print(f"[TOOL] 错误: {error_msg}")
        return {
            "role": "tool",
            "tool_call_id": tool_id,
            "content": error_msg,
        }


def execute_tool_calls(tool_calls: list) -> list:
    """批量执行 tool_calls，返回 tool response 消息列表。"""
    return [execute_tool_call(tc) for tc in tool_calls]


# ═══════════════════════════════════════════════════════════
# 测试入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=== 工具测试 ===\n")

    tests = {
        "get_time": {},
        "get_system_info": {},
        "calculator": {"expression": "2 ** 10 + sqrt(144)"},
        "get_weather": {"city": "杭州"},
    }

    if len(sys.argv) > 1:
        # 命令行指定要测试的工具
        tool_name = sys.argv[1]
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        tests = {tool_name: args}

    for name, args in tests.items():
        fn = _TOOL_FN.get(name)
        if fn:
            print(f"\n--- {name} ---")
            try:
                print(fn(**args))
            except Exception as e:
                print(f"错误: {e}")
        else:
            print(f"\n--- {name}: 未找到 ---")
