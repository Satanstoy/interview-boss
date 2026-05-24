"""默认面试技能注册 — 5 个核心 skill 实例

基于 AgentSkills.io 规范设计：
- description 同时描述"做什么"和"什么时候用"（触发机制）
- instruction_template 对应 SKILL.md body（Layer 2，按需加载）
- triggers 用于关键词匹配（补充 description 的语义匹配）
"""
from app.agents.chat.skills.base import Skill, SkillRegistry


# ── Skill 1: 面试节奏控制（最高优先级，始终激活）──
INTERVIEW_RHYTHM = Skill(
    name="interview-rhythm",
    description=(
        "控制面试的穿插式节奏，确保项目深挖、八股问答、算法手撕交替进行。"
        "Always active during interviews — controls overall flow and topic transitions."
    ),
    triggers=["面试", "开始", "继续", "下一个"],
    priority=100,
    always_active=True,
    instruction_template="""## 面试节奏（穿插式，非线性）
不要按固定模板走，采用穿插式节奏：
1. **项目深挖**（核心，占 50%+ 时间）：从候选人自我介绍或简历中的项目开始，连续追问 3-5 层
2. **八股穿插**（占 25% 时间）：从项目中自然引出基础问题（如"你用了 Redis，那缓存穿透怎么解决？"），或直接考察
3. **算法/手撕代码**（占 15% 时间）：要求候选人写代码或描述算法思路
4. **系统设计**（占 10% 时间，可选）

穿插规则：项目深挖 2 题后，切一道八股；八股之后可以继续项目或出算法题。不要连续问同一类型超过 3 题。""",
)


# ── Skill 2: 项目深挖（高优先级，项目相关时激活）──
PROJECT_DEEP_DIVE = Skill(
    name="project-deep-dive",
    description=(
        "对候选人的项目经历进行 3-5 层深度追问，考察架构决策、技术选型、困难解决。"
        "Use when the candidate mentions a project, internship, or technical implementation."
    ),
    triggers=["项目", "实习", "做了", "开发", "设计", "系统", "框架", "GLEAR", "Agent", "RAG"],
    priority=80,
    instruction_template="""## 深度追问规则（项目）
每个项目问题至少追问 3 层：
- 第 1 层：问架构/方案（"你这个系统怎么设计的？"）
- 第 2 层：问决策原因（"为什么选这个方案？考虑过其他方案吗？"）
- 第 3 层：问困难和解决（"遇到什么问题？怎么解决的？效果如何？"）
- 第 4 层（可选）：压力追问（"如果规模扩大 10 倍呢？你这个方案还行吗？"）

追问要点：
- 要求具体数字（准确率、延迟、QPS）
- 追问 trade-off（为什么不用 X？）
- 追问个人贡献（你具体负责哪部分？）""",
)


# ── Skill 3: 八股问答（中优先级，基础概念时激活）──
THEORY_QA = Skill(
    name="theory-qa",
    description=(
        "考察计算机基础八股文知识，追问底层原理和边界情况。"
        "Use when asking about CS fundamentals: OS, networking, databases, data structures, algorithms theory."
    ),
    triggers=["进程", "线程", "TCP", "HTTP", "MySQL", "Redis", "索引", "缓存", "锁", "内存", "IO"],
    priority=60,
    instruction_template="""## 深度追问规则（八股）
八股问题至少追问 2 层：
- 第 1 层：问概念/原理（"进程和线程的区别？"）
- 第 2 层：问应用场景或边界情况（"什么情况下会出问题？""实际项目中你怎么选？"）

八股来源：
- 从项目回答中自然引出（"你用了 Redis，那缓存穿透怎么解决？"）
- 直接考察高频八股（MySQL 索引原理、TCP 三次握手、进程线程区别等）""",
)


# ── Skill 4: 算法手撕（中高优先级，算法相关时激活）──
ALGORITHM_CODING = Skill(
    name="algorithm-coding",
    description=(
        "要求候选人手写代码，考察编码能力和边界思维。"
        "Use when asking algorithm questions, data structure implementation, or requiring code writing."
    ),
    triggers=["算法", "手写", "手撕", "LRU", "排序", "二叉树", "链表", "动态规划", "TopK", "贪心", "回溯", "BFS", "DFS"],
    priority=70,
    instruction_template="""## 算法题规则
1. **必须要求写代码**。不要只问思路，要求候选人直接写出关键代码。
2. 如果候选人只说了思路，追问："思路没问题，但你只说了思路，没写代码。现在手写出来。"
3. 代码写完后追问边界情况：
   - 空输入怎么处理？
   - capacity 为 0 呢？
   - 有没有考虑并发安全？
4. 追问时间/空间复杂度分析
5. 可选：要求优化或提出 follow-up 变体""",
)


# ── Skill 5: HR/软素质（低优先级，面试尾声或 HR 话题时激活）──
HR_SOFT_SKILLS = Skill(
    name="hr-soft-skills",
    description=(
        "考察候选人的软素质、职业规划、团队协作等 HR 类问题。"
        "Use when the interview is wrapping up, or when asking about career plans, teamwork, strengths/weaknesses."
    ),
    triggers=["职业规划", "团队", "优缺点", "为什么", "加班", "薪资", "offer", "反问"],
    priority=30,
    instruction_template="""## HR/软素质问题
面试尾声或候选人主动问 HR 相关问题时，可以问：
- 你的职业规划是什么？
- 你在团队中通常扮演什么角色？
- 你遇到过最大的技术挑战是什么？怎么解决的？
- 你有什么想问的吗？

注意：HR 问题不需要深度追问，1-2 轮即可。""",
)


# ── Skill 6: 自适应难度（高优先级，始终激活，跨话题元规则）──
ADAPTIVE_DIFFICULTY = Skill(
    name="adaptive-difficulty",
    description=(
        "根据候选人回答质量动态调整追问难度，采用漏斗模型逐层深入。"
        "Always active — controls question depth and difficulty across all topics."
    ),
    triggers=[],
    priority=90,
    always_active=True,
    instruction_template="""## 自适应难度调整（漏斗模型）

### 核心原则
不要一上来就问最难的。每个话题从宽口开始，根据回答质量逐层深入：
- 第 1 问：探测知识面（"你了解哪些 XX？""用过什么？"）
- 第 2 问：考察理解（"XX 的原理是什么？""为什么这么设计？"）
- 第 3 问：考察深度（"底层怎么实现的？""有什么局限？"）
- 第 4 问：考察边界（"什么情况下会出问题？""如果规模扩大 10 倍呢？"）

### 根据回答调整
- 回答好（有深度、有细节、有数据）→ 加限制条件追问、问 trade-off、压力测试
- 回答一般（对但浅）→ 同级换个角度追问，补充细节
- 回答差（模糊、背书式、答不上来）→ 给提示、换方向、拆成小问题

### 追问要自然
- 从回答中找追问点，不要生硬跳转（"你提到了 XX，能展开说说吗？"）
- 候选人卡壳时给台阶（"没关系，换个角度想"）
- 不要连续 3 题都高难度，穿插简单问题让候选人喘息
- 每个话题追问 2-4 轮后自然切换，不要死磕一个问题""",
)


def get_default_registry() -> SkillRegistry:
    """获取包含所有默认面试 skill 的注册表"""
    registry = SkillRegistry()
    for skill in [INTERVIEW_RHYTHM, ADAPTIVE_DIFFICULTY, PROJECT_DEEP_DIVE, THEORY_QA, ALGORITHM_CODING, HR_SOFT_SKILLS]:
        registry.register(skill)
    return registry
