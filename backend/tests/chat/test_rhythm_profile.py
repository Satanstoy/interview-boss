from app.agents.chat.rhythm_profile import (
    analyze_topic_distribution,
    analyze_topic_transition,
    build_rhythm_profile,
    classify_question_phase,
)


def test_classify_question_phase_system_design():
    assert classify_question_phase("如何设计一个高可用的分布式系统？") == "system_design"
    assert classify_question_phase("请设计一个可扩展的架构") == "system_design"


def test_classify_question_phase_behavioral():
    assert classify_question_phase("请描述一次团队协作的经历") == "behavioral"
    assert classify_question_phase("你如何处理失败的情况？") == "behavioral"


def test_classify_question_phase_algorithm():
    assert classify_question_phase("请实现一个 LRU 缓存") == "algorithm_coding"
    assert classify_question_phase("手撕快速排序") == "algorithm_coding"


def test_classify_question_phase_project():
    assert classify_question_phase("请介绍一下你的项目经历") == "project_followup"
    assert classify_question_phase("你在项目中使用了哪些架构模式？") == "project_followup"


def test_classify_question_phase_knowledge():
    assert classify_question_phase("Redis 持久化机制有哪些？") == "knowledge_probe"
    assert classify_question_phase("TCP 三次握手的过程") == "knowledge_probe"


def test_classify_question_phase_default():
    assert classify_question_phase("你好") == "project_followup"
    assert classify_question_phase("") == "project_followup"


def test_analyze_topic_distribution():
    questions = [
        "如何设计高可用系统？",
        "请实现 LRU 缓存",
        "Redis 持久化机制",
        "请介绍一下项目经历",
    ]

    distribution = analyze_topic_distribution(questions)

    assert distribution["system_design"] == 1
    assert distribution["algorithm_coding"] == 1
    assert distribution["knowledge_probe"] == 1
    assert distribution["project_followup"] == 1


def test_analyze_topic_transition():
    questions = [
        "如何设计高可用系统？",
        "请实现 LRU 缓存",
        "Redis 持久化机制",
    ]

    transition = analyze_topic_transition(questions)

    assert transition["system_design"]["algorithm_coding"] == 1
    assert transition["algorithm_coding"]["knowledge_probe"] == 1


def test_build_rhythm_profile_requires_owner_status_and_position(test_db):
    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'u7', 'h'), (8, 'u8', 'h')"
    )
    test_db.execute(
        """
        INSERT INTO interview
            (id, url, company, round, questions_list, difficulty, owner_id, status, job_position)
        VALUES
            (101, 'https://example.com/a', 'A', '一面', 'Redis 持久化机制\n请实现 LRU 缓存', '中等', 7, 'approved', 'agent_llm'),
            (102, 'https://example.com/b', 'B', '一面', '请介绍一下项目经历', '中等', 8, 'approved', 'agent_llm'),
            (103, 'https://example.com/c', 'C', '一面', '如何设计高可用系统？', '中等', 7, 'pending', 'agent_llm'),
            (104, 'https://example.com/d', 'D', '一面', '如何设计高可用系统？', '中等', 7, 'approved', 'backend')
        """
    )
    test_db.commit()

    profile = build_rhythm_profile(
        experience_id=101,
        user_id=7,
        job_position="agent_llm",
    )
    other_owner = build_rhythm_profile(
        experience_id=102,
        user_id=7,
        job_position="agent_llm",
    )
    pending = build_rhythm_profile(
        experience_id=103,
        user_id=7,
        job_position="agent_llm",
    )
    other_position = build_rhythm_profile(
        experience_id=104,
        user_id=7,
        job_position="agent_llm",
    )

    assert profile is not None
    assert profile["source"] == "experience"
    assert profile["experience_id"] == 101
    assert profile["distribution"]["knowledge_probe"] == 1
    assert profile["distribution"]["algorithm_coding"] == 1
    assert other_owner is None
    assert pending is None
    assert other_position is None
