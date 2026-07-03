"""Deepgram Speech-to-Text 服务

提供音频文件转录功能，支持多种音频格式。
"""

import os
import logging
from typing import Optional
from deepgram import DeepgramClient, PrerecordedOptions, FileSource

logger = logging.getLogger("interview-boss")

# Deepgram API 配置
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")


def get_deepgram_client() -> Optional[DeepgramClient]:
    """获取 Deepgram 客户端实例"""
    if not DEEPGRAM_API_KEY:
        logger.warning("DEEPGRAM_API_KEY 未配置，语音转录功能不可用")
        return None
    try:
        return DeepgramClient(DEEPGRAM_API_KEY)
    except Exception as e:
        logger.error(f"Deepgram 客户端初始化失败: {e}")
        return None


async def transcribe_audio(
    audio_data: bytes,
    filename: str,
    language: str = "zh",
    model: str = "nova-3",
) -> dict:
    """转录音频文件

    Args:
        audio_data: 音频文件二进制数据
        filename: 文件名（用于判断 MIME 类型）
        language: 语言代码（zh=中文, en=英文, ja=日文等）
        model: Deepgram 模型名称

    Returns:
        dict: 包含转录文本和元数据的字典
    """
    client = get_deepgram_client()
    if not client:
        return {
            "success": False,
            "error": "Deepgram API 未配置",
            "text": "",
        }

    try:
        # 根据文件扩展名设置 MIME 类型
        mime_type = _get_mime_type(filename)

        # 配置转录选项
        options = PrerecordedOptions(
            model=model,
            language=language,
            smart_format=True,
            diarize=False,
            punctuate=True,
            paragraphs=True,
            utterances=False,
        )

        # 执行转录
        source: FileSource = {"buffer": audio_data}
        response = await client.listen.asyncprerecorded.transcribe_file(source, options)

        # 提取转录结果
        transcript = response.results.channels[0].alternatives[0].transcript
        confidence = response.results.channels[0].alternatives[0].confidence

        # 提取字级时间戳（如果需要）
        words = []
        if response.results.channels[0].alternatives[0].words:
            for word in response.results.channels[0].alternatives[0].words:
                words.append(
                    {
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                        "confidence": word.confidence,
                    }
                )

        logger.info(
            f"音频转录完成: filename={filename}, "
            f"language={language}, model={model}, "
            f"transcript_length={len(transcript)}"
        )

        return {
            "success": True,
            "text": transcript.strip(),
            "confidence": confidence,
            "words": words,
            "model": model,
            "language": language,
        }

    except Exception as e:
        logger.error(f"音频转录失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "text": "",
        }


def _get_mime_type(filename: str) -> str:
    """根据文件扩展名获取 MIME 类型"""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    mime_map = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "webm": "audio/webm",
        "mp4": "audio/mp4",
        "mpeg": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
    }
    return mime_map.get(ext, "audio/wav")


def validate_audio_file(
    filename: str, file_size: int, max_size_mb: int = 25
) -> tuple[bool, str]:
    """验证音频文件

    Args:
        filename: 文件名
        file_size: 文件大小（字节）
        max_size_mb: 最大文件大小（MB）

    Returns:
        tuple: (是否有效, 错误信息)
    """
    # 检查文件扩展名
    allowed_extensions = {
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".m4a",
        ".webm",
        ".mp4",
        ".mpeg",
        ".opus",
        ".aac",
    }
    ext = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in allowed_extensions:
        return (
            False,
            f"不支持的音频格式: {ext}。支持的格式: {', '.join(allowed_extensions)}",
        )

    # 检查文件大小
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        return (
            False,
            f"文件大小超过限制: {file_size / 1024 / 1024:.1f}MB > {max_size_mb}MB",
        )

    return True, ""
