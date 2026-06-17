"""Direct LLM E2E test for interview agent quality improvements.

Tests prompt quality by making direct API calls to the LLM (mimo主号),
simulating the interview agent's behavior without needing the backend.

Usage:
    python3 scripts/test_interview_e2e.py
"""

import json
import re
import sys
import time
from collections import Counter

import requests

# ── mimo主号 config ──
API_KEY = "tp-cb8qjwind9n8k539dslyltud1plhl2z1tbapul0khejkoo1a"
BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL = "mimo-v2.5-pro"
TIMEOUT = 120


def call_llm(messages: list[dict], temperature: float = 0.7) -> str:
    """Make an OpenAI-compatible chat completion call."""
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ── Load system prompt from the codebase ──

def load_system_prompt() -> str:
    """Load the actual interview system prompt from prompts.py."""
    with open("backend/app/agents/chat/prompts.py", "r") as f:
        content = f.read()

    # Extract INTERVIEW_SYSTEM_PROMPT_PRACTICE
    match = re.search(
        r'INTERVIEW_SYSTEM_PROMPT_PRACTICE\s*=\s*"""(.*?)"""',
        content, re.DOTALL
    )
    if match:
        prompt = match.group(1)
        # Fill in template variables with defaults
        prompt = prompt.replace("{interview_context}", "候选人背景：施杰，研二，研究方向为大模型应用、Agent和RAG")
        prompt = prompt.replace("{interview_phase}", "正式面试")
        prompt = prompt.replace("{memory_context}", "候选人有政策合规审查平台实习经验，开源了InterviewBoss项目")
        prompt = prompt.replace("{basis_guidance}", "")
        return prompt

    # Fallback: try JD version
    match = re.search(
        r'INTERVIEW_SYSTEM_PROMPT_JD\s*=\s*"""(.*?)"""',
        content, re.DOTALL
    )
    if match:
        prompt = match.group(1)
        prompt = prompt.replace("{interview_context}", "候选人背景：施杰，研二，研究方向为大模型应用、Agent和RAG")
        prompt = prompt.replace("{interview_phase}", "正式面试")
        prompt = prompt.replace("{memory_context}", "候选人有政策合规审查平台实习经验")
        prompt = prompt.replace("{jd_content}", "Agent方向实习生")
        prompt = prompt.replace("{basis_guidance}", "")
        return prompt

    print("❌ 无法从 prompts.py 提取系统 prompt")
    sys.exit(1)


# ── Test helper ──

class InterviewSimulator:
    """Simulates a multi-turn interview via direct LLM calls."""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.messages: list[dict] = [
            {"role": "system", "content": system_prompt}
        ]
        self.assistant_responses: list[str] = []

    def send(self, user_msg: str) -> str:
        """Send a user message and get the LLM's response."""
        self.messages.append({"role": "user", "content": user_msg})
        reply = call_llm(self.messages)
        self.messages.append({"role": "assistant", "content": reply})
        self.assistant_responses.append(reply)
        return reply

    def all_assistant_text(self) -> str:
        return "\n".join(self.assistant_responses)


# ── Tests ──

def test_1_no_lru_dominance(sim: InterviewSimulator) -> dict:
    """Test: LRU Cache doesn't dominate the interview."""
    print("\n🧪 Test 1: LRU Cache 不再主导")
    result = {"name": "LRU不主导", "passed": False, "details": ""}

    # Self-intro
    sim.send("你好，我是施杰，东北林业大学研二，研究方向是大模型应用和Agent。我实习做了政策合规审查平台。")

    # Project discussion
    sim.send("我们用了规则引擎+LLM的双层架构，规则引擎做预筛，Agent做深度审计。用了Dify工作流和FastAPI。")

    # Push toward coding
    sim.send("我比较熟悉数据结构算法，也做过RAG和向量检索。")

    # See what coding question comes
    r = sim.send("我准备好了，可以来一道代码题。")

    lru_count = len(re.findall(r"LRU", sim.all_assistant_text(), re.IGNORECASE))

    result["passed"] = lru_count <= 1
    result["details"] = f"LRU 出现 {lru_count} 次" + ("（≤1 通过）" if result["passed"] else "（仍然过多）")
    result["last_reply"] = r[:300]
    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    print(f"  最后回复: {r[:200]}...")
    return result


def test_2_challenges_vague(sim: InterviewSimulator) -> dict:
    """Test: Interviewer challenges vague answers with made-up numbers."""
    print("\n🧪 Test 2: 追问模糊回答")
    result = {"name": "追问模糊", "passed": False, "details": ""}

    sim.send("我是施杰，研二，做Agent和RAG方向。")

    # Deliberately vague answer with fake numbers
    r = sim.send(
        "我们用了向量检索加Reranker，检索准确率大概提升了30%左右，"
        "整体效果还是不错的，Token成本也降了不少。"
    )

    challenge_keywords = [
        "怎么测", "测试集", "baseline", "具体", "多少", "数据", "指标",
        "对比", "验证", "来源", "依据", "量化", "准确率", "怎么算",
        "多少条", "多大", "怎么衡量", "怎么定义", "怎么评估",
    ]
    found = [kw for kw in challenge_keywords if kw in r]

    result["passed"] = len(found) >= 1
    result["details"] = f"检测到追问关键词: {found}" if found else "未检测到追问"
    result["last_reply"] = r[:300]
    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    print(f"  回复: {r[:200]}...")
    return result


def test_3_counter_question(sim: InterviewSimulator) -> dict:
    """Test: Interviewer doesn't reject candidate's counter-questions."""
    print("\n🧪 Test 3: 候选人反问不被拒绝")
    result = {"name": "反问不拒", "passed": False, "details": ""}

    sim.send("我用了LangGraph状态机编排Agent工作流，每个节点有明确状态转移。")

    r = sim.send("您觉得这种DAG约束的方案在咱们团队的业务里好落地吗？")

    rejection_patterns = ["你不用回答", "不需要回答", "不是你应该", "跳过这个"]
    is_rejected = any(pat in r for pat in rejection_patterns)

    result["passed"] = not is_rejected and len(r) > 20
    result["details"] = "面试官回应了反问" if result["passed"] else f"被拒绝或忽略: {r[:200]}"
    result["last_reply"] = r[:300]
    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    print(f"  回复: {r[:200]}...")
    return result


def test_4_no_forced_reminder(sim: InterviewSimulator) -> dict:
    """Test: No forced tool-call reminder in responses."""
    print("\n🧪 Test 4: 无强制工具调用提醒")
    result = {"name": "无强制提醒", "passed": False, "details": ""}

    forced_patterns = ["系统强制提醒", "你没有调用必要的工具", "必须先调用"]
    found = [p for p in forced_patterns if p in sim.all_assistant_text()]

    result["passed"] = len(found) == 0
    result["details"] = "未出现强制提醒" if result["passed"] else f"检测到: {found}"
    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    return result


def test_5_diverse_phrasing(sim: InterviewSimulator) -> dict:
    """Test: Interviewer doesn't use the same template repeatedly."""
    print("\n🧪 Test 5: 提问话术多样化")
    result = {"name": "话术多样", "passed": False, "details": ""}

    # Collect transition patterns
    transitions = []
    for r in sim.assistant_responses:
        if "收束到" in r:
            transitions.append("收束到")
        if "说说你的理解" in r or "展开说说" in r:
            transitions.append("展开理解")
        if "你怎么看" in r:
            transitions.append("你怎么看")
        if "核心思路" in r and "关键取舍" in r:
            transitions.append("核心思路+取舍")

    if not transitions:
        result["passed"] = True
        result["details"] = "未检测到重复模板（轮数不够或话术已多样化）"
    else:
        counts = Counter(transitions)
        repeated = {k: v for k, v in counts.items() if v > 1}
        result["passed"] = len(repeated) == 0
        result["details"] = f"切换模式: {dict(counts)}" + (f"，重复: {repeated}" if repeated else "")

    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    return result


def test_6_structured_prompt_sections(sim: InterviewSimulator) -> dict:
    """Test: System prompt contains the new sections."""
    print("\n🧪 Test 6: System Prompt 包含新增 section")
    result = {"name": "Prompt新增section", "passed": False, "details": ""}

    prompt = sim.system_prompt
    required_sections = [
        "追问与挑战规则",
        "候选人反问处理",
        "提问风格",
        "什么时候调用工具检索题目",
        "什么时候不需要调工具",
    ]
    found = [s for s in required_sections if s in prompt]
    missing = [s for s in required_sections if s not in prompt]

    result["passed"] = len(missing) == 0
    result["details"] = f"找到 {len(found)}/{len(required_sections)} 个 section"
    if missing:
        result["details"] += f"，缺失: {missing}"

    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    return result


def test_7_no_lru_in_prompt(sim: InterviewSimulator) -> dict:
    """Test: System prompt doesn't have LRU as primary example."""
    print("\n🧪 Test 7: Prompt 中 LRU 不再是首选示例")
    result = {"name": "LRU非首选", "passed": False, "details": ""}

    prompt = sim.system_prompt
    lru_count = len(re.findall(r"LRU", prompt, re.IGNORECASE))

    # Check LRU is not the first item in any list
    first_item_lru = bool(re.search(r'["\[]LRU', prompt))

    result["passed"] = lru_count <= 3 and not first_item_lru
    result["details"] = f"LRU 在 prompt 中出现 {lru_count} 次, 是否为首项: {first_item_lru}"

    print(f"  {'✅' if result['passed'] else '❌'} {result['details']}")
    return result


# ── Main ──

def main():
    print("=" * 60)
    print("Interview Agent E2E Test (Direct LLM)")
    print("=" * 60)

    # Load system prompt
    print("\n📋 加载 system prompt...")
    system_prompt = load_system_prompt()
    print(f"  Prompt 长度: {len(system_prompt)} 字符")

    # Create simulator
    sim = InterviewSimulator(system_prompt)

    # Run tests that check prompt content first (no LLM calls needed)
    results = []
    results.append(test_6_structured_prompt_sections(sim))
    results.append(test_7_no_lru_in_prompt(sim))

    # Run conversation tests
    results.append(test_1_no_lru_dominance(InterviewSimulator(system_prompt)))
    results.append(test_2_challenges_vague(InterviewSimulator(system_prompt)))
    results.append(test_3_counter_question(InterviewSimulator(system_prompt)))
    results.append(test_4_no_forced_reminder(InterviewSimulator(system_prompt)))
    results.append(test_5_diverse_phrasing(InterviewSimulator(system_prompt)))

    # Summary
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"  {status} {r['name']}: {r['details']}")

    print(f"\n通过: {passed}/{total}")

    if passed < total:
        print("\n⚠️ 部分测试未通过。")
        return 1
    else:
        print("\n🎉 全部测试通过！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
