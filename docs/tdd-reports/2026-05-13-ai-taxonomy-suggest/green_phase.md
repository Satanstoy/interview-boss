# 绿灯阶段报告

**测试编号:** T-001 ~ T-006
**实现时间:** 2026-05-13

## 最小实现代码

```python
# backend/app/services/taxonomy_suggest.py

async def generate_taxonomy_suggestion(position: str, user_id: int = None) -> List[Dict]:
    """调用LLM生成分类体系建议"""
    if not position or not position.strip():
        raise ValueError("岗位名不能为空")

    prompt = GENERATE_TAXONOMY_PROMPT.format(position=position.strip())
    response = await raw_llm_call(user_id=user_id, messages=[...], temperature=0.7)
    return _parse_taxonomy_response(response)
```

## 测试运行结果（预期：✅ 绿色）

```bash
$ /root/.local/bin/uv run pytest backend/tests/test_taxonomy_suggest.py -v

============================= test session starts ==============================
backend/tests/test_taxonomy_suggest.py::TestGenerateTaxonomy::test_generate_taxonomy_returns_valid_structure PASSED [ 20%]
backend/tests/test_taxonomy_suggest.py::TestGenerateTaxonomy::test_empty_position_name_raises_error PASSED [ 40%]
backend/tests/test_taxonomy_suggest.py::TestGenerateTaxonomy::test_invalid_llm_response_raises_error PASSED [ 60%]
backend/tests/test_taxonomy_suggest.py::TestGenerateTaxonomy::test_llm_timeout_raises_error PASSED [ 80%]
backend/tests/test_taxonomy_suggest.py::TestGenerateTaxonomy::test_save_taxonomy_updates_database PASSED [100%]

============================== 5 passed in 3.44s ==============================
```

## 实现说明
- 核心服务函数 `generate_taxonomy_suggestion()` 负责调用LLM并解析响应
- `_parse_taxonomy_response()` 处理JSON提取和格式验证
- `save_taxonomy_suggestion()` 封装数据库保存逻辑
- 使用 `raw_llm_call()` 复用现有的LLM调用基础设施

## 阶段状态
- [x] 最小实现已编写
- [x] 测试通过（绿色）
- [ ] 进入重构阶段
