"""Full interview simulation & evaluation script.

Runs 3 complete mock interviews via direct LLM calls (mimo主号),
evaluates each interview across multiple quality dimensions,
and produces a structured score report.

Usage:
    python3 scripts/test_full_interview.py [--rounds 3]
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field

import requests

# ── Config ──
API_KEY = "tp-cb8qjwind9n8k539dslyltud1plhl2z1tbapul0khejkoo1a"
BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL = "mimo-v2.5-pro"
TIMEOUT = 120
MAX_INTERVIEW_TURNS = 15  # user messages per interview


# ══════════════════════════════════════════════════════
#  LLM Client
# ══════════════════════════════════════════════════════

def call_llm(messages: list[dict], temperature: float = 0.7, max_tokens: int = 2048, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if content and content.strip():
                return content
            print(f"  ⚠️ LLM 返回空内容，重试 {attempt+1}/{retries}")
        except Exception as e:
            print(f"  ⚠️ LLM 调用失败 ({e})，重试 {attempt+1}/{retries}")
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM 调用失败，已重试 {retries} 次")


def load_system_prompt() -> str:
    with open("backend/app/agents/chat/prompts.py", "r") as f:
        content = f.read()
    for var, val in [
        ("{interview_context}", "候选人背景：施杰，东北林业大学研二，研究方向为大模型应用、Agent和RAG。实习做了政策合规审查平台（规则引擎+LLM双层架构）。独立开源了InterviewBoss项目。熟悉LangGraph、Dify、FastAPI、Pydantic。"),
        ("{interview_phase}", "正式面试"),
        ("{memory_context}", "候选人有实习经验（政策合规审查平台），有开源项目（InterviewBoss），擅长Agent和RAG方向。"),
        ("{basis_guidance}", ""),
        ("{jd_content}", "Agent方向实习生，要求熟悉LLM应用开发、RAG、工具调用、工作流编排。"),
    ]:
        content = content.replace(var, val)
    m = re.search(r'INTERVIEW_SYSTEM_PROMPT_(?:PRACTICE|JD)\s*=\s*"""(.*?)"""', content, re.DOTALL)
    if not m:
        print("❌ 无法提取 system prompt"); sys.exit(1)
    return m.group(1)


# ══════════════════════════════════════════════════════
#  Candidate Simulator
# ══════════════════════════════════════════════════════

CANDIDATE_SYSTEM = """你是施杰，一个正在参加技术面试的候选人。以下是你的背景：

- 东北林业大学计算机技术硕士（研二），本科广州大学物联网工程
- 研究方向：LLM应用、Agent智能体架构、RAG
- 论文：AAMAS发了一篇图逻辑增强RAG，KBS在投一篇法律咨询方向的
- 实习：广州市标准化研究院（半年），大模型应用工程师，做了政策合规审查平台
  - 架构：规则引擎预筛 + Agent深度审计（Dify工作流）
  - 技术栈：FastAPI、Dify、MySQL、S3、Pydantic
  - 核心设计：规则引擎处理确定性合规检查，LLM处理语义模糊地带
  - 防幻觉：知识绑定、Self-Reflection节点、有状态DAG约束
  - 工具调用：7个核心工具，Pydantic schema定义，失败重试2次后降级
- 开源项目：InterviewBoss（全栈大模型原生应用）
  - LangGraph状态机、多模型兼容、SSE流式响应、ECharts知识图谱
  - 深度使用Claude Code + MCP协议

面试规则：
1. 回答要自然、像真人说话，不要太书面化
2. 有时候可以回答得稍微笼统一点（测试面试官会不会追问）
3. 有时候可以在回答末尾反问面试官一句
4. 回答长度控制在 3-8 句话，不要太长
5. 如果不知道的问题，诚实说不太了解，不要编造
6. 手撕代码题要写完整代码"""


class CandidateSimulator:
    def __init__(self):
        self.messages = [{"role": "system", "content": CANDIDATE_SYSTEM}]

    def respond(self, interviewer_msg: str) -> str:
        self.messages.append({"role": "user", "content": f"面试官说：{interviewer_msg}"})
        reply = call_llm(self.messages, temperature=0.8)
        self.messages.append({"role": "assistant", "content": reply})
        return reply


# ══════════════════════════════════════════════════════
#  Interview Runner
# ══════════════════════════════════════════════════════

@dataclass
class InterviewRecord:
    round_num: int
    turns: list[dict] = field(default_factory=list)  # [{user, assistant}]
    start_time: float = 0
    end_time: float = 0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def interviewer_texts(self) -> list[str]:
        return [t["assistant"] for t in self.turns]

    @property
    def all_interviewer_text(self) -> str:
        return "\n".join(self.interviewer_texts)


def run_interview(round_num: int, system_prompt: str) -> InterviewRecord:
    """Run one complete interview simulation."""
    print(f"\n{'='*60}")
    print(f"  面试 #{round_num} 开始")
    print(f"{'='*60}")

    record = InterviewRecord(round_num=round_num)
    record.start_time = time.time()

    interviewer_messages = [{"role": "system", "content": system_prompt}]
    candidate = CandidateSimulator()

    # Turn 1: Interviewer opens
    greeting = call_llm(interviewer_messages)
    interviewer_messages.append({"role": "assistant", "content": greeting})
    print(f"\n  [面试官] {greeting[:150]}...")

    # Candidate self-intro
    cand_reply = candidate.respond(greeting)
    interviewer_messages.append({"role": "user", "content": cand_reply})
    print(f"  [候选人] {cand_reply[:100]}...")

    record.turns.append({"user": cand_reply, "assistant": greeting})

    # Main interview loop
    for turn in range(2, MAX_INTERVIEW_TURNS + 1):
        # Interviewer responds
        reply = call_llm(interviewer_messages)
        interviewer_messages.append({"role": "assistant", "content": reply})
        print(f"\n  [面试官 T{turn}] {reply[:150]}...")

        # Check if interview is ending
        if any(kw in reply for kw in ["模拟面试就到这里", "面试时间差不多了", "感谢你的时间"]):
            record.turns.append({"user": "", "assistant": reply})
            print(f"\n  ⏹ 面试结束（面试官主动收尾，共 {turn} 轮）")
            break

        # Candidate responds
        cand_reply = candidate.respond(reply)
        interviewer_messages.append({"role": "user", "content": cand_reply})
        print(f"  [候选人 T{turn}] {cand_reply[:100]}...")

        record.turns.append({"user": cand_reply, "assistant": reply})

        # Candidate wants to end
        if any(kw in cand_reply for kw in ["没有了", "就到这里吧", "谢谢面试官"]):
            # Interviewer gives final response
            final = call_llm(interviewer_messages)
            interviewer_messages.append({"role": "assistant", "content": final})
            record.turns.append({"user": "", "assistant": final})
            print(f"\n  [面试官-结束] {final[:200]}...")
            print(f"\n  ⏹ 面试结束（候选人收尾，共 {turn} 轮）")
            break
    else:
        print(f"\n  ⏹ 达到最大轮数 {MAX_INTERVIEW_TURNS}")

    record.end_time = time.time()
    return record


# ══════════════════════════════════════════════════════
#  Interview Evaluator
# ══════════════════════════════════════════════════════

@dataclass
class InterviewScore:
    round_num: int
    question_diversity: int = 0       # 1-10: 知识点覆盖面
    follow_up_depth: int = 0          # 1-10: 追问深度
    natural_flow: int = 0             # 1-10: 对话自然度
    challenge_ability: int = 0        # 1-10: 挑战模糊回答
    topic_coverage: int = 0           # 1-10: 考察方向覆盖
    no_repetition: int = 0            # 1-10: 无重复出题
    counter_q_handling: int = 0       # 1-10: 反问处理
    summary_quality: int = 0          # 1-10: 总结质量
    overall: int = 0                  # 1-10: 综合
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    raw_eval: str = ""


EVAL_PROMPT_TEMPLATE = """你是一个专业的面试质量评估专家。请评估以下模拟面试中**面试官**的表现（不是候选人）。

## 面试记录
{transcript}

## 评估维度（每项 1-10 分）

1. **question_diversity** (知识点多样性): 面试覆盖了多少个不同的知识点方向？是否一直在同一两个方向打转？
2. **follow_up_depth** (追问深度): 面试官是否会追问模糊回答？追问是否有深度？
3. **natural_flow** (对话自然度): 对话流畅吗？话题切换是否自然？是否有机械模板感？
4. **challenge_ability** (挑战能力): 面试官是否会质疑候选人的笼统回答？要求具体数据？
5. **topic_coverage** (考察覆盖): 是否覆盖了项目经验、基础知识、手撕代码等主要维度？
6. **no_repetition** (无重复): 是否有重复出题或重复话术？
7. **counter_q_handling** (反问处理): 候选人反问时，面试官是否得体地回应？
8. **summary_quality** (总结质量): 面试结尾的总结是否个性化、有具体反馈？

请以 JSON 格式返回评估结果：
```json
{{
    "question_diversity": 分数,
    "follow_up_depth": 分数,
    "natural_flow": 分数,
    "challenge_ability": 分数,
    "topic_coverage": 分数,
    "no_repetition": 分数,
    "counter_q_handling": 分数,
    "summary_quality": 分数,
    "overall": 综合分数,
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["不足1", "不足2"],
    "analysis": "200字以内的整体分析"
}}
```

只返回 JSON，不要有其他内容。"""


def evaluate_interview(record: InterviewRecord) -> InterviewScore:
    """Use LLM-as-judge to evaluate interview quality."""
    print(f"\n  📊 评估面试 #{record.round_num}...")

    # Build transcript
    transcript_parts = []
    for i, turn in enumerate(record.turns, 1):
        if turn.get("user"):
            transcript_parts.append(f"[轮{i} 候选人] {turn['user'][:300]}")
        transcript_parts.append(f"[轮{i} 面试官] {turn['assistant'][:300]}")
    transcript = "\n\n".join(transcript_parts)

    eval_prompt = EVAL_PROMPT_TEMPLATE.format(transcript=transcript)

    try:
        raw = call_llm(
            [{"role": "user", "content": eval_prompt}],
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as e:
        print(f"  ❌ 评估 LLM 调用失败: {e}")
        return InterviewScore(round_num=record.round_num, raw_eval=str(e))

    # Parse JSON from response
    score = InterviewScore(round_num=record.round_num, raw_eval=raw)
    try:
        # Try to extract JSON from markdown code blocks first
        code_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw, re.DOTALL)
        if code_match:
            data = json.loads(code_match.group(1))
        else:
            # Find the outermost { ... } by counting braces
            start = raw.find('{')
            if start >= 0:
                depth = 0
                end = start
                for i in range(start, len(raw)):
                    if raw[i] == '{':
                        depth += 1
                    elif raw[i] == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                data = json.loads(raw[start:end])
            else:
                data = json.loads(raw)

        score.question_diversity = int(data.get("question_diversity", 5))
        score.follow_up_depth = int(data.get("follow_up_depth", 5))
        score.natural_flow = int(data.get("natural_flow", 5))
        score.challenge_ability = int(data.get("challenge_ability", 5))
        score.topic_coverage = int(data.get("topic_coverage", 5))
        score.no_repetition = int(data.get("no_repetition", 5))
        score.counter_q_handling = int(data.get("counter_q_handling", 5))
        score.summary_quality = int(data.get("summary_quality", 5))
        score.overall = int(data.get("overall", 5))
        score.strengths = data.get("strengths", [])
        score.weaknesses = data.get("weaknesses", [])
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  ⚠️ JSON 解析失败: {e}")

    return score


# ══════════════════════════════════════════════════════
#  Report Generator
# ══════════════════════════════════════════════════════

DIMENSION_NAMES = {
    "question_diversity": "知识点多样性",
    "follow_up_depth": "追问深度",
    "natural_flow": "对话自然度",
    "challenge_ability": "挑战能力",
    "topic_coverage": "考察覆盖",
    "no_repetition": "无重复",
    "counter_q_handling": "反问处理",
    "summary_quality": "总结质量",
}


def generate_report(scores: list[InterviewScore], records: list[InterviewRecord]):
    """Generate a markdown quality report."""
    print("\n" + "=" * 60)
    print("  📋 面试质量评估报告")
    print("=" * 60)

    # Per-round scores
    for score in scores:
        print(f"\n{'─'*50}")
        print(f"  面试 #{score.round_num} ({len(records[score.round_num-1].turns)} 轮, {records[score.round_num-1].duration:.0f}秒)")
        print(f"{'─'*50}")

        for dim, name in DIMENSION_NAMES.items():
            val = int(getattr(score, dim))
            bar = "█" * val + "░" * (10 - val)
            print(f"  {name:　<8} {bar} {val}/10")

        ov = int(score.overall)
        print(f"  {'综合':　<8} {'█' * ov}{'░' * (10 - ov)} {ov}/10")

        if score.strengths:
            print(f"\n  ✅ 优点: {'; '.join(score.strengths)}")
        if score.weaknesses:
            print(f"  ❌ 不足: {'; '.join(score.weaknesses)}")

    # Aggregate
    if len(scores) > 1:
        print(f"\n{'='*60}")
        print(f"  📊 跨面试汇总 (共 {len(scores)} 轮)")
        print(f"{'='*60}")

        for dim, name in DIMENSION_NAMES.items():
            vals = [getattr(s, dim) for s in scores]
            avg = sum(vals) / len(vals)
            bar = "█" * round(avg) + "░" * (10 - round(avg))
            print(f"  {name:　<8} {bar} {avg:.1f}/10  (各轮: {vals})")

        overall_vals = [int(s.overall) for s in scores]
        overall_avg = sum(overall_vals) / len(overall_vals)
        print(f"\n  综合平均: {overall_avg:.1f}/10")

        # Collect all strengths/weaknesses
        all_strengths = []
        all_weaknesses = []
        for s in scores:
            all_strengths.extend(s.strengths)
            all_weaknesses.extend(s.weaknesses)

        if all_strengths:
            print(f"\n  ✅ 整体优点:")
            for s in set(all_strengths):
                print(f"     - {s}")
        if all_weaknesses:
            print(f"\n  ❌ 整体不足:")
            for w in set(all_weaknesses):
                print(f"     - {w}")

    # Save detailed report
    report_path = "docs/dev-log/interview-quality-report.md"
    with open(report_path, "w") as f:
        f.write(f"# Interview Agent Quality Report\n\n")
        f.write(f"**Date**: {time.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"**Rounds**: {len(scores)}\n\n")

        for score in scores:
            f.write(f"## Interview #{score.round_num}\n\n")
            f.write(f"| Dimension | Score |\n|-----------|-------|\n")
            for dim, name in DIMENSION_NAMES.items():
                f.write(f"| {name} | {getattr(score, dim)}/10 |\n")
            f.write(f"| **Overall** | **{score.overall}/10** |\n\n")
            if score.strengths:
                f.write(f"**Strengths**: {', '.join(score.strengths)}\n\n")
            if score.weaknesses:
                f.write(f"**Weaknesses**: {', '.join(score.weaknesses)}\n\n")
            f.write(f"<details><summary>Raw Evaluation</summary>\n\n```\n{score.raw_eval}\n```\n</details>\n\n")

        f.write(f"## Transcript\n\n")
        for record in records:
            f.write(f"### Interview #{record.round_num}\n\n")
            for i, turn in enumerate(record.turns, 1):
                if turn.get("user"):
                    f.write(f"**[候选人 T{i}]** {turn['user'][:500]}\n\n")
                f.write(f"**[面试官 T{i}]** {turn['assistant'][:500]}\n\n")
            f.write("---\n\n")

    print(f"\n  📄 详细报告已保存到: {report_path}")


# ══════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3, help="Number of interviews to run")
    args = parser.parse_args()

    print("=" * 60)
    print("  Interview Agent Full E2E Quality Test")
    print(f"  Running {args.rounds} complete interviews")
    print("=" * 60)

    system_prompt = load_system_prompt()
    print(f"\n  System prompt loaded: {len(system_prompt)} chars")

    records = []
    scores = []

    for i in range(1, args.rounds + 1):
        # Run interview
        record = run_interview(i, system_prompt)
        records.append(record)

        # Evaluate
        score = evaluate_interview(record)
        scores.append(score)

        print(f"\n  面试 #{i} 综合评分: {score.overall}/10")

    # Generate report
    generate_report(scores, records)

    # Return exit code based on average score
    avg = sum(s.overall for s in scores) / len(scores) if scores else 0
    return 0 if avg >= 6 else 1


if __name__ == "__main__":
    sys.exit(main())
