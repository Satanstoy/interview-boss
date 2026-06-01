"""
自动化测试 — 针对 BUG-001, BUG-002
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestTaxonomyErrorHandling:
    """BUG-001, BUG-002: 错误处理改进"""

    @pytest.mark.asyncio
    async def test_llm_500_error_provides_detailed_message(self):
        """LLM服务返回500时，应该提供详细的错误信息"""
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"

        # Mock LLM调用抛出500错误
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Error code: 500 - {'status': 500, 'error': 'Internal Server Error'}")

            # Act & Assert
            with pytest.raises(Exception, match="LLM服务内部错误"):
                await generate_taxonomy_suggestion(position, user_id=1)

    @pytest.mark.asyncio
    async def test_connection_error_provides_detailed_message(self):
        """网络连接失败时，应该提供详细的错误信息"""
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"

        # Mock LLM调用抛出连接错误
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Connection error: failed to connect")

            # Act & Assert
            with pytest.raises(Exception, match="网络连接失败"):
                await generate_taxonomy_suggestion(position, user_id=1)

    @pytest.mark.asyncio
    async def test_auth_error_provides_detailed_message(self):
        """认证失败时，应该提供详细的错误信息"""
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"

        # Mock LLM调用抛出认证错误
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Error code: 401 - Unauthorized")

            # Act & Assert
            with pytest.raises(Exception, match="LLM服务认证失败"):
                await generate_taxonomy_suggestion(position, user_id=1)

    @pytest.mark.asyncio
    async def test_timeout_error_still_raises_timeout(self):
        """超时错误应该仍然抛出TimeoutError"""
        from app.services.taxonomy_suggest import generate_taxonomy_suggestion

        position = "后端开发工程师"

        # Mock LLM调用抛出超时错误
        with patch('app.services.taxonomy_suggest.raw_llm_call', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = TimeoutError("LLM调用超时")

            # Act & Assert
            with pytest.raises(TimeoutError):
                await generate_taxonomy_suggestion(position, user_id=1)
