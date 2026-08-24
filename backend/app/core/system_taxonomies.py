"""System-owned taxonomies for the positions currently supported by the app.

The values in this module are canonical classification data.  They are used
for cross-user clustering and public-bank processing, so user-owned taxonomy
rows must never replace them at runtime.
"""

from __future__ import annotations


def _taxonomy(position: str, categories: list[dict[str, object]], tags: list[str]) -> dict:
    return {
        "job_position": position,
        "categories": categories,
        "tags": tags,
    }


SYSTEM_TAXONOMIES = {
    "agent开发/大模型应用开发/大模型开发": _taxonomy(
        "agent开发/大模型应用开发/大模型开发",
        [
            {"cat1": "A.项目经验与设计", "children": ["A1.项目介绍与背景", "A2.系统架构设计", "A3.难点攻关与优化", "A4.反思与改进"]},
            {"cat1": "B.Agent与LLM应用", "children": ["B1.Agent架构与范式", "B2.RAG系统设计", "B3.工具调用与协议集成", "B4.记忆与上下文管理", "B5.Prompt工程", "B6.评估安全与优化", "B7.AI Coding与代码智能", "B8.模型与框架选型"]},
            {"cat1": "C.基础工程能力", "children": ["C1.编程语言基础", "C2.框架与中间件", "C3.数据库基础", "C4.操作系统与网络"]},
            {"cat1": "D.分布式与高并发", "children": ["D1.缓存设计与优化", "D2.高并发与限流", "D3.分布式事务与一致性"]},
            {"cat1": "E.算法与数据结构", "children": ["E1.算法手撕与数据结构"]},
        ],
        [
            "Agent架构设计", "多智能体协作", "MCP协议", "A2A协议", "工具调用", "函数调用",
            "RAG设计", "Agentic RAG", "向量数据库", "混合检索", "知识图谱", "记忆管理",
            "上下文管理", "KV Cache", "Prompt工程", "提示词优化", "ReAct/推理范式", "规划与分解",
            "模型评估", "Agent评估", "幻觉应对", "安全防护", "微调/SFT", "AI Coding", "代码沙箱",
            "模型选型", "Agent框架对比", "Java并发", "Redis", "Spring/AOP", "分布式事务",
            "高并发限流", "MySQL", "Linux/网络", "算法手撕", "系统设计",
        ],
    ),
    "后端开发": _taxonomy(
        "后端开发",
        [
            {"cat1": "A.编程语言与基础", "children": ["A1.语法基础", "A2.面向对象编程", "A3.并发与多线程", "A4.错误处理与异常", "A5.内存管理与垃圾回收", "A6.标准库与框架"]},
            {"cat1": "B.数据库与存储", "children": ["B1.关系型数据库", "B2.NoSQL数据库", "B3.数据库设计与范式", "B4.SQL查询与优化", "B5.数据库事务与锁", "B6.分布式数据库"]},
            {"cat1": "C.系统设计与架构", "children": ["C1.设计模式", "C2.微服务架构", "C3.负载均衡与高可用", "C4.缓存策略", "C5.消息队列与异步处理", "C6.系统监控与日志"]},
            {"cat1": "D.网络与通信", "children": ["D1.HTTP/HTTPS协议", "D2.TCP/IP与网络模型", "D3.网络安全", "D4.RESTful API设计", "D5.WebSocket与实时通信", "D6.网络编程与Socket"]},
            {"cat1": "E.算法与数据结构", "children": ["E1.排序与搜索算法", "E2.数据结构", "E3.动态规划", "E4.图算法", "E5.复杂度分析", "E6.算法应用"]},
            {"cat1": "F.开发工具与实践", "children": ["F1.版本控制", "F2.单元测试与集成测试", "F3.持续集成/持续部署", "F4.代码审查与编码规范", "F5.容器化与DevOps", "F6.性能优化与调试"]},
        ],
        [
            "Java", "Python", "Go", "C++", "面向对象", "并发编程", "JVM", "垃圾回收",
            "Spring", "Spring Boot", "MySQL", "PostgreSQL", "Redis", "MongoDB", "SQL优化",
            "事务与锁", "分库分表", "微服务", "RPC", "消息队列", "Kafka", "RabbitMQ", "缓存",
            "高并发", "限流", "负载均衡", "高可用", "HTTP", "TCP/IP", "RESTful API", "网络安全",
            "算法", "数据结构", "Docker", "Kubernetes", "CI/CD", "单元测试", "性能优化", "系统设计",
        ],
    ),
    "前端开发": _taxonomy(
        "前端开发",
        [
            {"cat1": "A.JavaScript与语言基础", "children": ["A1.JavaScript核心", "A2.TypeScript类型系统", "A3.异步与事件循环", "A4.模块化与代码组织"]},
            {"cat1": "B.浏览器与Web基础", "children": ["B1.HTML与CSS", "B2.DOM与浏览器渲染", "B3.HTTP与网络通信", "B4.浏览器存储与安全"]},
            {"cat1": "C.框架与工程化", "children": ["C1.Vue与React", "C2.组件化设计", "C3.状态管理", "C4.构建工具与依赖管理", "C5.前端测试"]},
            {"cat1": "D.性能与用户体验", "children": ["D1.加载性能优化", "D2.运行时性能优化", "D3.兼容性与可访问性", "D4.监控与稳定性"]},
            {"cat1": "E.应用架构与协作", "children": ["E1.前端应用架构", "E2.SSR与全栈协作", "E3.API与数据流设计", "E4.项目经验与难点"]},
            {"cat1": "F.算法与编码能力", "children": ["F1.数据结构", "F2.算法实现", "F3.手写代码与调试"]},
        ],
        [
            "JavaScript", "TypeScript", "HTML", "CSS", "DOM", "浏览器原理", "事件循环", "HTTP",
            "WebSocket", "Vue", "React", "Node.js", "组件化", "状态管理", "前端工程化", "Vite",
            "Webpack", "SSR/SSG", "前端安全", "性能优化", "兼容性", "可访问性", "单元测试",
            "E2E测试", "监控与埋点", "算法", "数据结构", "API设计", "系统设计",
        ],
    ),
    "全栈开发": _taxonomy(
        "全栈开发",
        [
            {"cat1": "A.前端基础与应用", "children": ["A1.JavaScript与TypeScript", "A2.HTML与CSS", "A3.前端框架与组件化", "A4.状态管理与数据流"]},
            {"cat1": "B.后端服务与接口", "children": ["B1.服务端语言与框架", "B2.API与协议设计", "B3.认证授权与安全", "B4.异步任务与消息处理"]},
            {"cat1": "C.数据与存储", "children": ["C1.关系型数据库", "C2.NoSQL与缓存", "C3.数据建模与查询优化", "C4.事务与一致性"]},
            {"cat1": "D.系统架构与交付", "children": ["D1.全栈应用架构", "D2.部署与容器化", "D3.CI/CD与环境管理", "D4.可观测性与高可用"]},
            {"cat1": "E.工程质量与性能", "children": ["E1.测试策略", "E2.性能优化", "E3.故障排查", "E4.代码规范与协作"]},
            {"cat1": "F.算法与综合设计", "children": ["F1.数据结构与算法", "F2.系统设计", "F3.项目经验与难点"]},
        ],
        [
            "JavaScript", "TypeScript", "Vue", "React", "Node.js", "Python", "Java", "Go", "RESTful API",
            "GraphQL", "认证授权", "OAuth/JWT", "MySQL", "PostgreSQL", "Redis", "MongoDB", "SQL优化",
            "事务与一致性", "消息队列", "Docker", "Kubernetes", "CI/CD", "云服务", "监控与日志",
            "性能优化", "自动化测试", "前端安全", "网络安全", "算法", "数据结构", "系统设计",
        ],
    ),
    "测试开发": _taxonomy(
        "测试开发",
        [
            {"cat1": "A.测试基础与策略", "children": ["A1.测试流程与方法", "A2.测试计划与风险", "A3.测试用例设计", "A4.缺陷管理与质量度量"]},
            {"cat1": "B.功能与接口测试", "children": ["B1.功能测试", "B2.接口测试", "B3.测试数据与环境", "B4.兼容性与异常场景"]},
            {"cat1": "C.自动化测试开发", "children": ["C1.UI自动化", "C2.API自动化", "C3.测试框架设计", "C4.Mock与服务虚拟化", "C5.自动化稳定性"]},
            {"cat1": "D.质量工程与交付", "children": ["D1.持续集成与测试流水线", "D2.代码质量与门禁", "D3.测试左移与右移", "D4.质量平台建设"]},
            {"cat1": "E.性能安全与可靠性", "children": ["E1.性能测试", "E2.压力与容量评估", "E3.安全测试", "E4.故障注入与可靠性"]},
            {"cat1": "F.编程与问题定位", "children": ["F1.编程语言基础", "F2.数据结构与算法", "F3.日志分析与故障排查"]},
        ],
        [
            "测试用例", "等价类", "边界值", "场景法", "缺陷分析", "接口测试", "功能测试", "UI自动化",
            "API自动化", "Selenium", "Playwright", "Cypress", "pytest", "JUnit", "Mock", "契约测试",
            "测试数据", "SQL", "性能测试", "压力测试", "容量评估", "JMeter", "安全测试", "故障注入",
            "CI/CD", "质量门禁", "测试平台", "日志分析", "稳定性", "算法", "数据结构",
        ],
    ),
}
