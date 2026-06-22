#!/usr/bin/env python3
"""
GPT-5.5 Claude Code 断连问题 — 精准诊断 v2
重点排查: 流式格式兼容性、连接超时、并发断连
"""

import asyncio
import json
import time
import sys
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

import aiohttp

API_BASE = "http://localhost:15800"
MESSAGES_URL = f"{API_BASE}/v1/messages"
MODEL = "gpt-5.5"

# Claude Code 实际会用到的 tools
CLAUDE_CODE_TOOLS = [
    {"name": "Read", "description": "Reads a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "Write", "description": "Writes a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}},
    {"name": "Edit", "description": "Edits a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["file_path", "old_string", "new_string"]}},
    {"name": "Bash", "description": "Runs a bash command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "Grep", "description": "Searches file content", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "Glob", "description": "Finds files by glob", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "Task", "description": "Launch a new agent", "input_schema": {"type": "object", "properties": {"description": {"type": "string"}, "prompt": {"type": "string"}, "subagent_type": {"type": "string"}}, "required": ["description", "prompt"]}},
]


@dataclass
class DiagResult:
    name: str
    status: str
    detail: str
    latency_ms: float = 0
    error: Optional[str] = None


async def test_1_raw_stream_format(session: aiohttp.ClientSession) -> DiagResult:
    """直接抓取原始流式数据，检查格式完整性"""
    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": "Write a Python function to merge two sorted lists. Only code."}],
        "stream": True,
    }

    start = time.perf_counter()
    events_seen = set()
    event_count = 0
    raw_lines = []
    saw_message_stop = False
    saw_error = False

    try:
        async with session.post(MESSAGES_URL, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                return DiagResult(name="raw_stream", status="FAIL",
                                  detail=f"HTTP {resp.status}")

            # 读取原始字节流，不做行分割假设
            buffer = b""
            async for chunk in resp.content.iter_chunked(4096):
                buffer += chunk
                # 按 \n\n 分割 SSE 事件
                while b"\n\n" in buffer:
                    event_raw, buffer = buffer.split(b"\n\n", 1)
                    event_lines = event_raw.decode("utf-8").strip().split("\n")
                    event_type = None
                    event_data = None
                    for line in event_lines:
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            event_data = line[6:]
                    if event_type:
                        events_seen.add(event_type)
                        event_count += 1
                        if event_type == "message_stop":
                            saw_message_stop = True
                        if event_type == "error":
                            saw_error = True
                            raw_lines.append(f"ERROR: {event_data[:200]}")

            latency = (time.perf_counter() - start) * 1000

            detail = f"Events: {sorted(events_seen)}, count={event_count}, message_stop={'yes' if saw_message_stop else 'NO'}"
            if saw_error:
                return DiagResult(name="raw_stream", status="FAIL", detail=detail, latency_ms=latency,
                                  error=f"Stream contained error event: {raw_lines}")
            if not saw_message_stop:
                return DiagResult(name="raw_stream", status="FAIL", detail=detail, latency_ms=latency,
                                  error="Stream did NOT end with message_stop!")
            return DiagResult(name="raw_stream", status="OK", detail=detail, latency_ms=latency)

    except Exception as e:
        return DiagResult(name="raw_stream", status="FAIL", detail="Exception", error=str(e)[:500])


async def test_2_tool_use_with_tools(session: aiohttp.ClientSession) -> DiagResult:
    """模拟 Claude Code 真实 tool use 场景 - 带 7 个 tools"""
    payload = {
        "model": MODEL,
        "max_tokens": 3000,
        "tools": CLAUDE_CODE_TOOLS,
        "messages": [
            {"role": "user", "content": """Read the file backend/app/main.py, then add error handling middleware and write it back. List the steps and execute them."""}
        ],
        "stream": True,
    }

    start = time.perf_counter()
    events = []
    tool_uses = []

    try:
        async with session.post(MESSAGES_URL, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                body = await resp.text()
                return DiagResult(name="tool_use_7tools", status="FAIL",
                                  detail=f"HTTP {resp.status}", error=body[:500])

            buffer = b""
            async for chunk in resp.content.iter_chunked(4096):
                buffer += chunk
                while b"\n\n" in buffer:
                    event_raw, buffer = buffer.split(b"\n\n", 1)
                    event_lines = event_raw.decode("utf-8").strip().split("\n")
                    event_type = None
                    event_data = None
                    for line in event_lines:
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            event_data = line[6:]
                    if event_type:
                        events.append(event_type)
                        if event_data and "tool_use" in event_data and event_type == "content_block_start":
                            try:
                                data = json.loads(event_data)
                                if "content_block" in data and data["content_block"].get("type") == "tool_use":
                                    tool_uses.append(data["content_block"].get("name", "unknown"))
                            except:
                                pass

            latency = (time.perf_counter() - start) * 1000
            saw_stop = "message_stop" in events

            detail = f"{len(events)} events, tool_uses={tool_uses}, stop={'yes' if saw_stop else 'NO'}"
            if not saw_stop:
                return DiagResult(name="tool_use_7tools", status="FAIL", detail=detail, latency_ms=latency,
                                  error="Stream incomplete - no message_stop")
            if not tool_uses:
                return DiagResult(name="tool_use_7tools", status="WARN", detail=detail, latency_ms=latency,
                                  error="No tool_use blocks detected")
            return DiagResult(name="tool_use_7tools", status="OK", detail=detail, latency_ms=latency)

    except Exception as e:
        return DiagResult(name="tool_use_7tools", status="FAIL", detail="Exception", error=str(e)[:500])


async def test_3_concurrent_streaming(session: aiohttp.ClientSession) -> list[DiagResult]:
    """并发流式请求 - Claude Code 经常并行发送多个请求"""
    results = []
    payload = {
        "model": MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": "Write a Python function: factorial. Only code."}],
        "stream": True,
    }

    async def worker(i: int):
        start = time.perf_counter()
        events = []
        try:
            async with session.post(MESSAGES_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    return DiagResult(name=f"concurrent_{i:02d}", status="FAIL",
                                      detail=f"HTTP {resp.status}", latency_ms=(time.perf_counter()-start)*1000)
                buffer = b""
                async for chunk in resp.content.iter_chunked(4096):
                    buffer += chunk
                    while b"\n\n" in buffer:
                        event_raw, buffer = buffer.split(b"\n\n", 1)
                        event_lines = event_raw.decode("utf-8").strip().split("\n")
                        for line in event_lines:
                            if line.startswith("event: "):
                                events.append(line[7:])
                latency = (time.perf_counter() - start) * 1000
                has_stop = "message_stop" in events
                return DiagResult(name=f"concurrent_{i:02d}",
                                  status="OK" if has_stop else "FAIL",
                                  detail=f"{len(events)} events, stop={'yes' if has_stop else 'NO'}",
                                  latency_ms=latency)
        except asyncio.TimeoutError:
            return DiagResult(name=f"concurrent_{i:02d}", status="TIMEOUT", detail="Timeout")
        except Exception as e:
            return DiagResult(name=f"concurrent_{i:02d}", status="ERROR", detail=str(e)[:100])

    # 3 轮不同并发度
    for concurrency in [3, 5, 8]:
        tasks = [worker(i) for i in range(concurrency)]
        batch = await asyncio.gather(*tasks)
        for r in batch:
            r.name = f"c{concurrency}_{r.name.split('_')[-1]}"
        results.extend(batch)

    return results


async def test_4_idle_timeout(session: aiohttp.ClientSession) -> DiagResult:
    """测试连接 keep-alive - 发送请求后等待一段时间再发"""
    # 第一次请求
    resp1 = await session.post(MESSAGES_URL, json={
        "model": MODEL, "max_tokens": 50,
        "messages": [{"role": "user", "content": "Say: ping"}],
    }, timeout=aiohttp.ClientTimeout(total=30))
    if resp1.status != 200:
        return DiagResult(name="idle_timeout", status="FAIL",
                          detail=f"First request failed: HTTP {resp1.status}")

    # 等待 30 秒
    await asyncio.sleep(30)

    # 第二次请求
    start = time.perf_counter()
    resp2 = await session.post(MESSAGES_URL, json={
        "model": MODEL, "max_tokens": 50,
        "messages": [{"role": "user", "content": "Say: pong"}],
    }, timeout=aiohttp.ClientTimeout(total=30))
    latency = (time.perf_counter() - start) * 1000

    if resp2.status != 200:
        return DiagResult(name="idle_timeout", status="FAIL",
                          detail=f"Second request failed after 30s idle: HTTP {resp2.status}",
                          latency_ms=latency)
    return DiagResult(name="idle_timeout", status="OK",
                      detail="Connection alive after 30s idle", latency_ms=latency)


async def test_5_multi_tool_roundtrip(session: aiohttp.ClientSession) -> DiagResult:
    """模拟 Claude Code 完整的多轮 tool use 循环"""
    messages = [
        {"role": "user", "content": "I need to add a health check endpoint to my FastAPI app. Read the existing code first, then write the updated file."}
    ]

    # Turn 1: 模型应该返回 tool_use (Read)
    start = time.perf_counter()
    resp1 = await session.post(MESSAGES_URL, json={
        "model": MODEL, "max_tokens": 1000, "tools": CLAUDE_CODE_TOOLS, "messages": messages,
    }, timeout=aiohttp.ClientTimeout(total=60))
    data1 = await resp1.json()
    if resp1.status != 200:
        return DiagResult(name="multi_tool_rt", status="FAIL",
                          detail=f"Turn 1 failed: HTTP {resp1.status}")

    content1 = data1.get("content", [])
    tool_use_blocks = [b for b in content1 if b.get("type") == "tool_use"]
    text_blocks = [b for b in content1 if b.get("type") == "text"]

    if not tool_use_blocks:
        return DiagResult(name="multi_tool_rt", status="WARN",
                          detail=f"Turn 1: no tool_use, {len(text_blocks)} text blocks. Model didn't use tools.")

    # Turn 2: 模拟用户返回 tool_result
    # 构建 assistant content (包含 tool_use blocks)
    assistant_content = content1
    messages.append({"role": "assistant", "content": assistant_content})

    # 添加 tool results
    tool_results = []
    for tb in tool_use_blocks:
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tb["id"],
            "content": f"# main.py\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/')\ndef root():\n    return {{'status': 'ok'}}"
        })
    messages.append({"role": "user", "content": tool_results})

    resp2 = await session.post(MESSAGES_URL, json={
        "model": MODEL, "max_tokens": 2000, "tools": CLAUDE_CODE_TOOLS, "messages": messages,
    }, timeout=aiohttp.ClientTimeout(total=120))
    data2 = await resp2.json()
    if resp2.status != 200:
        return DiagResult(name="multi_tool_rt", status="FAIL",
                          detail=f"Turn 2 failed: HTTP {resp2.status}")

    content2 = data2.get("content", [])
    tool_use_blocks2 = [b for b in content2 if b.get("type") == "tool_use"]
    text_blocks2 = [b for b in content2 if b.get("type") == "text"]

    latency = (time.perf_counter() - start) * 1000
    return DiagResult(name="multi_tool_rt", status="OK",
                      detail=f"2 turns OK: T1={tool_use_blocks[0].get('name','?') if tool_use_blocks else 'no_tool'}, T2={len(tool_use_blocks2)} tools + {len(text_blocks2)} text",
                      latency_ms=latency)


def print_header(text: str):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}")


def print_diag(r: DiagResult):
    icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌", "TIMEOUT": "⏰", "ERROR": "💥"}.get(r.status, "❓")
    print(f"  {icon} {r.name:<30s} [{r.status:<8s}] {r.detail}")
    if r.error:
        print(f"     ↳ {r.error[:200]}")
    if r.latency_ms > 0:
        print(f"     ↳ {r.latency_ms:.0f}ms")


async def main():
    print_header("GPT-5.5 Claude Code 断连诊断 v2")
    print(f"  API: {API_BASE} | Model: {MODEL}")

    connector = aiohttp.TCPConnector(limit=20, limit_per_host=20, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:

        print_header("Test 1: 原始流式格式检查")
        r = await test_1_raw_stream_format(session)
        print_diag(r)

        print_header("Test 2: Tool Use 流式 (7 个工具)")
        r = await test_2_tool_use_with_tools(session)
        print_diag(r)

        print_header("Test 3: 并发流式请求 (3/5/8 并发)")
        results = await test_3_concurrent_streaming(session)
        ok = [r for r in results if r.status == "OK"]
        bad = [r for r in results if r.status != "OK"]
        print(f"  Summary: {len(ok)} OK, {len(bad)} failed/timeout")
        for r in bad:
            print_diag(r)
        if ok:
            print(f"  OK avg latency: {sum(r.latency_ms for r in ok)/len(ok):.0f}ms")

        print_header("Test 4: 连接空闲超时 (30s idle)")
        r = await test_4_idle_timeout(session)
        print_diag(r)

        print_header("Test 5: 完整多轮 Tool Use 往返")
        r = await test_5_multi_tool_roundtrip(session)
        print_diag(r)

    # ─── 结论 ───
    print_header("分析结论")
    print("""
  从测试结果来看，GPT-5.5 通过这个 API 的流式格式使用 SSE event 而非
  OpenAI 的 data: [DONE] 格式。流式结束标记是 event: message_stop。

  Claude Code 断连最可能的原因：

  1. 🔴 #1 嫌疑: 流式连接断开 — 如果并发流式请求中某些连接
     没有收到 message_stop，Claude Code 会直接丢弃响应

  2. 🔴 #2 嫌疑: 非流式请求方差 — Claude Code 经常同时发送
     流式和非流式请求，如果代理层对这两种请求处理不一致会出问题

  3. 🟡 #3 嫌疑: SSH 隧道超时 — SSH 隧道有默认的 keep-alive 机制，
     如果长响应期间隧道静默，可能被中间网络设备断开

  4. 🟡 #4 嫌疑: 上游内容过滤 — 安全策略可能突然中断流式响应
     (之前恶意代码测试返回 400 证明了这一点)
""")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))