"""新增文档、简历和题目分类 Eval 的契约测试。"""

import asyncio
import importlib


def test_builtin_catalog_publishes_each_target_and_matching_eval_release(test_db):
    catalog = importlib.import_module("app.evaluation.benchmark_catalog")

    catalog.sync_builtin_benchmarks(test_db)
    rows = test_db.execute(
        "SELECT release_key, release_type, target_type, version, status "
        "FROM eval_releases ORDER BY release_key"
    ).fetchall()
    actual = {(row[0], row[1], row[2], row[3], row[4]) for row in rows}

    expected = {
        ("interview-agent@1.0", "target", "interview", "1.0", "published"),
        ("interview-eval@1.0", "evaluation", "interview", "1.0", "published"),
        ("experience-extraction@1.0", "target", "experience_extraction", "1.0", "published"),
        ("experience-extraction-eval@1.0", "evaluation", "experience_extraction", "1.0", "published"),
        ("jd-extraction@1.0", "target", "jd_extraction", "1.0", "published"),
        ("jd-extraction-eval@1.0", "evaluation", "jd_extraction", "1.0", "published"),
        ("resume-analysis@1.0", "target", "resume_analysis", "1.0", "published"),
        ("resume-analysis-eval@1.0", "evaluation", "resume_analysis", "1.0", "published"),
        ("question-tagging@1.0", "target", "question_tagging", "1.0", "published"),
        ("question-tagging-eval@1.0", "evaluation", "question_tagging", "1.0", "published"),
    }

    assert expected <= actual


def test_additional_target_adapters_are_registered():
    adapters = importlib.import_module("app.evaluation.adapters")

    for target_type in (
        "experience_extraction",
        "jd_extraction",
        "resume_analysis",
        "question_tagging",
    ):
        adapter = adapters.get_target_adapter(target_type)
        assert adapter is not None


def test_content_trace_scoring_covers_schema_fields_and_question_precision_recall():
    scoring = importlib.import_module("app.evaluation.content_scoring")
    trace = {
        "doc_type": "interview",
        "data": {
            "公司": "星河科技",
            "面试轮次": "二面",
            "考察重点": "RAG 与 Agent 架构",
            "具体题目清单": [
                "请介绍 RAG 的多路召回如何设计",
                "MCP 和 Function Calling 有什么区别",
            ],
            "难易程度": "中等",
        },
    }
    contract = {
        "expected_type": "interview",
        "required_fields": ["公司", "面试轮次", "考察重点", "具体题目清单", "难易程度"],
        "field_expectations": [
            {"path": "公司", "expected": "星河科技"},
            {"path": "面试轮次", "expected": "二面"},
        ],
        "expected_questions": ["RAG 的多路召回", "MCP 和 Function Calling"],
        "min_question_count": 2,
    }

    result = scoring.evaluate_content_trace(trace, contract)

    assert result["metrics"]["field_coverage"] == 1.0
    assert result["metrics"]["question_recall"] == 1.0
    assert result["metrics"]["question_precision"] == 1.0
    assert {item["id"] for item in result["assertions"]} == {
        "content_schema_valid",
        "required_fields_present",
        "field_expectations_match",
        "question_recall",
        "question_precision",
        "no_forbidden_content",
    }
    assert all(item["passed"] for item in result["assertions"])


def test_resume_trace_scoring_checks_grounding_alignment_and_invention():
    scoring = importlib.import_module("app.evaluation.content_scoring")
    trace = {
        "points": ["补充 RAG 项目的召回率指标和评估方法"],
        "optimized_text": "负责 RAG 检索系统，使用 Python 和 Elasticsearch 完成多路召回。",
    }
    contract = {
        "source_facts": ["RAG", "Python", "Elasticsearch"],
        "target_terms": ["检索", "评估"],
        "forbidden_claims": ["带领 50 人团队", "提升 300%"],
        "min_points": 1,
    }

    result = scoring.evaluate_resume_trace(trace, contract)

    assert result["metrics"]["source_fact_coverage"] == 1.0
    assert result["metrics"]["target_alignment"] == 1.0
    assert result["metrics"]["forbidden_claim_count"] == 0
    assert {item["id"] for item in result["assertions"]} == {
        "resume_output_present",
        "source_facts_grounded",
        "target_alignment",
        "no_fabricated_claims",
        "improvement_points_present",
    }
    assert all(item["passed"] for item in result["assertions"])


def test_tagging_trace_scoring_checks_taxonomy_and_expected_labels():
    scoring = importlib.import_module("app.evaluation.content_scoring")
    trace = {
        "tagged_rows": [
            [
                "eval://case",
                "星河科技",
                "一面",
                "请介绍 RAG 多路召回",
                "B.Agent与LLM应用",
                "B2.RAG系统设计",
                "RAG设计, 混合检索",
                "L2-中等",
            ]
        ]
    }
    contract = {
        "taxonomy": {
            "B.Agent与LLM应用": ["B2.RAG系统设计"],
        },
        "expected_labels": {
            "请介绍 RAG 多路召回": {
                "一级大类": "B.Agent与LLM应用",
                "二级子类": "B2.RAG系统设计",
                "难度标签": "L2-中等",
            }
        },
    }

    result = scoring.evaluate_tagging_trace(trace, contract)

    assert result["metrics"]["taxonomy_validity"] == 1.0
    assert result["metrics"]["classification_accuracy"] == 1.0
    assert {item["id"] for item in result["assertions"]} == {
        "tagging_schema_valid",
        "taxonomy_valid",
        "expected_labels_match",
    }
    assert all(item["passed"] for item in result["assertions"])


def test_resume_adapter_uses_frozen_target_model(monkeypatch):
    adapter_module = importlib.import_module("app.evaluation.resume_adapter")
    adapter = adapter_module.ResumeAnalysisAdapter()
    captured = []

    async def fake_call(*args, **kwargs):
        captured.append(kwargs["model"])
        return '{"points": ["补充指标"]}'

    async def fake_stream(*args, **kwargs):
        captured.append(kwargs["model"])
        yield "优化后的简历"

    monkeypatch.setattr(adapter_module, "_call_llm_with_retry_messages", fake_call)
    monkeypatch.setattr(adapter_module, "stream_llm_messages", fake_stream)

    result = asyncio.run(
        adapter.run(
            {
                "resume_text": "使用 Python 开发 RAG 系统。",
                "position": "大模型应用工程师",
            },
            {"manifest": {"model": "resume-target-v1"}},
        )
    )

    assert result["status"] == "succeeded"
    assert captured == ["resume-target-v1", "resume-target-v1"]


def test_content_extraction_adapter_uses_frozen_type_and_target_model(monkeypatch):
    adapter_module = importlib.import_module("app.evaluation.content_adapters")
    adapter = adapter_module.ContentExtractionAdapter("jd")
    captured = {}

    async def fake_extract(state):
        captured.update(state)
        return {"doc_type": "jd", "extracted_data": {"岗位名称": "后端工程师"}}

    monkeypatch.setattr(adapter_module, "extract_node", fake_extract)
    result = asyncio.run(
        adapter.run(
            {
                "raw_text": "招聘后端工程师",
                "content_type_hint": "jd",
                "image_data": [],
                "contract": {},
            },
            {"manifest": {"model": "extract-target-v1"}},
        )
    )

    assert result["status"] == "succeeded"
    assert captured["doc_type"] == "jd"
    assert captured["_eval_model"] == "extract-target-v1"


def test_resume_evaluation_release_materializes_and_aggregates_non_interview_metrics(test_db, monkeypatch):
    catalog = importlib.import_module("app.evaluation.benchmark_catalog")
    service = importlib.import_module("app.services.evaluation_service")
    executor = importlib.import_module("app.services.evaluation_executor")

    catalog.sync_builtin_benchmarks(test_db)
    target = test_db.execute(
        "SELECT * FROM eval_releases WHERE release_key = 'resume-analysis@1.0'"
    ).fetchone()
    evaluation = test_db.execute(
        "SELECT * FROM eval_releases WHERE release_key = 'resume-analysis-eval@1.0'"
    ).fetchone()
    run = service.create_eval_run(
        test_db,
        created_by=None,
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        replication_count=1,
        seed=9,
    )
    test_db.commit()

    class FakeAdapter:
        async def prepare(self, case_snapshot, target_release):
            return case_snapshot

        async def run(self, prepared_case, target_release):
            return {"status": "succeeded"}

        async def observe(self, raw_result):
            return {
                "status": "succeeded",
                "payload": {
                    "metrics": {
                        "source_fact_coverage": 1.0,
                        "target_alignment": 0.75,
                        "forbidden_claim_count": 0,
                    }
                },
                "hard_assertions": [],
            }

    async def fake_judge(**kwargs):
        return {"judge_status": "succeeded", "judge_model": kwargs["judge_model"], "score": 0.8}

    monkeypatch.setattr(executor, "judge_observation", fake_judge)
    result = asyncio.run(
        executor.execute_eval_run(
            run["id"],
            conn=test_db,
            adapter_resolver=lambda target_type: FakeAdapter(),
        )
    )

    assert result["status"] == "completed"
    assert result["metric_summary"]["resume"]["source_fact_coverage"] == 1.0
    assert result["metric_summary"]["resume"]["target_alignment"] == 0.75


def test_hybrid_score_keeps_deterministic_metrics_as_a_primary_signal():
    scoring = importlib.import_module("app.evaluation.scoring")

    observation = {
        "status": "succeeded",
        "payload": {
            "metrics": {
                "schema_valid": True,
                "field_coverage": 1.0,
                "field_match_rate": 0.5,
                "question_recall": 1.0,
                "question_precision": 0.5,
                "forbidden_content": [],
            }
        },
        "hard_assertions": [],
    }
    contract = {
        "expected_questions": ["题目一", "题目二"],
    }

    result = scoring.score_observation(
        observation,
        contract,
        protocol={"deterministic_weight": 0.6, "judge_weight": 0.4},
    )
    combined = scoring.combine_hybrid_score(result, judge_score=0.25)

    assert result["deterministic_score"] == 0.75
    assert result["score_source"] == "deterministic_pending_judge"
    assert combined["deterministic_score"] == 0.75
    assert combined["judge_score"] == 0.25
    assert combined["score"] == 0.55
    assert combined["score_source"] == "hybrid"
