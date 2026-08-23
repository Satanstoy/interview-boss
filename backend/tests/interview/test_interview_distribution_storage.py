"""Storage contract for interview-distribution facts."""


def test_migration_adds_linked_typed_question_detail_fields(test_db):
    columns = {row["name"] for row in test_db.execute("PRAGMA table_info(questions_detail)")}

    assert {"interview_id", "question_type", "dimension"} <= columns
    assert test_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'interview_distribution_stats'"
    ).fetchone()
    assert test_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'interview_distribution_refresh_jobs'"
    ).fetchone()
    assert test_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_interview_distribution_preferences'"
    ).fetchone()


def test_question_type_mapper_returns_only_canonical_values():
    from app.services.interview_distribution import QuestionType, map_question_type

    assert map_question_type("E.算法与数据结构", "", "", "") is QuestionType.ALGORITHM_CODING
    assert map_question_type("A.项目经验与设计", "A3.难点攻关与优化", "", "") is QuestionType.PROJECT_FOLLOWUP
    assert map_question_type("", "", "", "") is QuestionType.UNCLASSIFIED


def test_question_type_mapper_recognizes_taxonomy_v11_language_categories():
    from app.services.interview_distribution import QuestionType, map_question_type

    assert map_question_type(
        "B.Java/Python语言与运行时", "B5.Python异步与并发", "", "asyncio 协程"
    ) is QuestionType.KNOWLEDGE_PROBE
    assert map_question_type(
        "C.Agent编排与工具", "C2.工具调用与MCP协议", "", "MCP 工具调用"
    ) is QuestionType.KNOWLEDGE_PROBE
