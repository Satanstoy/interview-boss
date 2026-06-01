"""
TDD 开发的测试模块 - AI智能生成分类体系

采用测试驱动开发（Test-Driven Development）方法编写。
遵循红-绿-重构（Red-Green-Refactor）循环：
- 🔴 阶段：先写测试，预期失败
- 🟢 阶段：写最少代码让测试通过
- 🔵 阶段：重构优化代码结构
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Any


class TestGenerateTaxonomy:
    """
    AI生成分类体系测试套件

    遵循 TDD 原则，每个测试对应一个用户需求或场景。
    测试命名规范：test_<场景>_<预期行为>
    """

    # =========================================================
    # T-001: 正常场景测试 - LLM返回有效分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_generate_taxonomy_returns_valid_structure(self):
        """
        LLM返回的有效JSON应被正确解析为分类结构

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange - 准备测试数据
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"
        mock_llm_response = '''```json
[
    {"cat1": "A.基础能力", "children": ["A1.Java基础", "A2.数据结构与算法"]},
    {"cat1": "B.框架与中间件", "children": ["B1.Spring框架", "B2.MyBatis"]}
]
```'''

        # Mock LLM调用
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_response

            # Act - 执行被测函数
            result = await generate_taxonomy_suggestion(position, user_id=1)

            # Assert - 验证结果
            assert isinstance(result, list)
            assert len(result) == 2
            assert "cat1" in result[0]
            assert "children" in result[0]
            assert isinstance(result[0]["children"], list)
            assert len(result[0]["children"]) == 2

    # =========================================================
    # T-005: 边界条件 - 空岗位名
    # =========================================================
    @pytest.mark.asyncio
    async def test_empty_position_name_raises_error(self):
        """
        空岗位名应抛出ValueError

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        # Act & Assert
        with pytest.raises(ValueError, match="岗位名不能为空"):
            await generate_taxonomy_suggestion("")

    # =========================================================
    # T-004: 异常处理 - LLM返回格式异常
    # =========================================================
    @pytest.mark.asyncio
    async def test_invalid_llm_response_raises_error(self):
        """
        LLM返回非JSON格式时应抛出错误

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"
        mock_llm_response = "这不是一个JSON格式的响应"

        # Mock LLM调用
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_response

            # Act & Assert
            with pytest.raises(ValueError, match="LLM返回的分类格式无效"):
                await generate_taxonomy_suggestion(position, user_id=1)

    # =========================================================
    # T-006: 异常处理 - LLM调用超时
    # =========================================================
    @pytest.mark.asyncio
    async def test_llm_timeout_raises_error(self):
        """
        LLM调用超时时应抛出超时错误

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"

        # Mock LLM调用抛出超时异常
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = TimeoutError("LLM调用超时")

            # Act & Assert
            with pytest.raises(TimeoutError):
                await generate_taxonomy_suggestion(position, user_id=1)

    # =========================================================
    # T-002: 保存分类到数据库
    # =========================================================
    @pytest.mark.asyncio
    async def test_save_taxonomy_updates_database(self):
        """
        调用保存函数后，taxonomy表应被更新

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.services.taxonomy_suggest import save_taxonomy_suggestion

        position = "后端开发工程师"
        categories = [
            {"cat1": "A.基础能力", "children": ["A1.Java基础", "A2.数据结构与算法"]},
            {"cat1": "B.框架与中间件", "children": ["B1.Spring框架", "B2.MyBatis"]}
        ]

        # Mock数据库操作
        with patch('app.services.taxonomy_suggest.save_taxonomy_for_position') as mock_save:
            # Act
            save_taxonomy_suggestion(position, categories)

            # Assert
            mock_save.assert_called_once_with(position, categories)
