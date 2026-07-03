"""音频 API — 语音转文字"""

import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional
from app.core.auth import get_current_user
from app.services import deepgram_service

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/audio")


class TranscribeResponse(BaseModel):
    """转录响应模型"""

    success: bool
    text: str = ""
    confidence: float = 0.0
    words: list[dict] = Field(default_factory=list)
    model: str = ""
    language: str = ""
    error: Optional[str] = None


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form(default="zh"),
    model: str = Form(default="nova-3"),
    user: dict = Depends(get_current_user),
):
    """将音频文件转录为文本

    支持的音频格式: mp3, wav, ogg, flac, m4a, webm, mp4, opus, aac
    最大文件大小: 25MB

    Args:
        file: 音频文件
        language: 语言代码（zh=中文, en=英文, ja=日文等）
        model: Deepgram 模型名称（nova-3, nova-2, whisper-large-v3 等）
        user: 当前用户（认证）

    Returns:
        TranscribeResponse: 转录结果
    """
    # 验证文件是否存在
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供音频文件")

    try:
        # 读取文件内容
        content = await file.read()
        file_size = len(content)

        # 验证音频文件
        is_valid, error_msg = deepgram_service.validate_audio_file(
            file.filename, file_size
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        # 执行转录
        result = await deepgram_service.transcribe_audio(
            audio_data=content,
            filename=file.filename,
            language=language,
            model=model,
        )

        if not result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"音频转录失败: {result.get('error', '未知错误')}",
            )

        return TranscribeResponse(
            success=True,
            text=result["text"],
            confidence=result.get("confidence", 0.0),
            words=result.get("words", []),
            model=result.get("model", model),
            language=result.get("language", language),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"音频转录接口异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="音频转录服务异常")


@router.get("/models")
async def list_models(user: dict = Depends(get_current_user)):
    """获取可用的 Deepgram 模型列表"""
    models = [
        {
            "id": "nova-3",
            "name": "Nova-3",
            "description": "最新模型，支持 36+ 语言，最佳准确率",
            "languages": ["zh", "en", "ja", "ko", "es", "fr", "de"],
        },
        {
            "id": "nova-2",
            "name": "Nova-2",
            "description": "高性能模型，支持实时流式转录",
            "languages": ["zh", "en", "ja", "ko", "es", "fr", "de"],
        },
        {
            "id": "whisper-large-v3",
            "name": "Whisper Large V3",
            "description": "OpenAI Whisper 模型，99+ 语言支持",
            "languages": ["zh", "en", "ja", "ko", "es", "fr", "de", "ru", "pt", "it"],
        },
    ]
    return {"status": "success", "data": models}


@router.get("/languages")
async def list_languages(user: dict = Depends(get_current_user)):
    """获取支持的语言列表"""
    languages = [
        {"code": "zh", "name": "中文", "native": "中文"},
        {"code": "en", "name": "English", "native": "English"},
        {"code": "ja", "name": "Japanese", "native": "日本語"},
        {"code": "ko", "name": "Korean", "native": "한국어"},
        {"code": "es", "name": "Spanish", "native": "Español"},
        {"code": "fr", "name": "French", "native": "Français"},
        {"code": "de", "name": "German", "native": "Deutsch"},
        {"code": "ru", "name": "Russian", "native": "Русский"},
        {"code": "pt", "name": "Portuguese", "native": "Português"},
        {"code": "it", "name": "Italian", "native": "Italiano"},
    ]
    return {"status": "success", "data": languages}
