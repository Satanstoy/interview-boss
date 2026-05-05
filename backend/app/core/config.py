import os
import logging
from dotenv import load_dotenv, set_key

load_dotenv()

logger = logging.getLogger("interview-boss")

DATA_DIR = "/root/sj/multimodal-parser/backend/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "multimodal.db")
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "gpt-4o")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.85"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024  # 默认 10MB

LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")
EMBEDDING_API_KEY = os.environ.get("OPENAI_API_KEY_EMBEDDING", "")
EMBEDDING_BASE_URL = os.environ.get("OPENAI_BASE_URL_EMBEDDING", "")

# 字段白名单（用于 GenericUpdateRequest 安全校验）
ALLOWED_UPDATE_COLUMNS = {
    "master_question_bank": {"question", "cat1", "cat2", "tags", "difficulty", "ai_answer", "is_starred"},
    "question_bank": {"question", "cat1", "cat2", "tags", "difficulty", "ai_answer", "is_starred"},
    "jd": {"url", "company", "job_title", "salary", "tech_stack", "bonus"},
    "interview": {"url", "company", "round", "focus", "questions_list", "difficulty", "season"},
    "questions_detail": {"url", "company", "round", "question", "cat1", "cat2", "tags", "diff_tag"},
}


def get_profile_setting(key: str, default: str = "") -> str:
    """从 user_profile 表读取配置值"""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute("SELECT value FROM user_profile WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return default


def _reload_from_db():
    """从数据库加载用户配置，覆盖模块级常量（启动时 + 配置更新后调用）"""
    global LLM_MODEL, EMBEDDING_MODEL, SIMILARITY_THRESHOLD, LLM_TIMEOUT
    global LLM_API_KEY, LLM_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_BASE_URL

    db_llm = get_profile_setting("llm_model")
    db_emb = get_profile_setting("embedding_model")
    db_sim = get_profile_setting("similarity_threshold")
    db_llm_key = get_profile_setting("llm_api_key")
    db_llm_url = get_profile_setting("llm_base_url")
    db_emb_key = get_profile_setting("embedding_api_key")
    db_emb_url = get_profile_setting("embedding_base_url")
    db_timeout = get_profile_setting("llm_timeout")

    if db_llm:
        LLM_MODEL = db_llm
    if db_emb:
        EMBEDDING_MODEL = db_emb
    if db_sim:
        try:
            SIMILARITY_THRESHOLD = float(db_sim)
        except ValueError:
            pass
    if db_timeout:
        try:
            LLM_TIMEOUT = int(db_timeout)
        except ValueError:
            pass
    if db_llm_key:
        LLM_API_KEY = db_llm_key
    if db_llm_url:
        LLM_BASE_URL = db_llm_url
    if db_emb_key:
        EMBEDDING_API_KEY = db_emb_key
    if db_emb_url:
        EMBEDDING_BASE_URL = db_emb_url

    logger.info(f"配置已加载: LLM_MODEL={LLM_MODEL}, EMBEDDING_MODEL={EMBEDDING_MODEL}, SIMILARITY_THRESHOLD={SIMILARITY_THRESHOLD}")

    # 重建 LLM 客户端
    try:
        from app.services.llm import rebuild_clients
        rebuild_clients()
    except Exception as e:
        logger.warning(f"重建 LLM 客户端失败: {e}")


# user_profile key → .env 变量名的映射
_ENV_KEY_MAP = {
    "llm_api_key": "OPENAI_API_KEY",
    "llm_base_url": "OPENAI_BASE_URL",
    "llm_model": "LLM_MODEL_NAME",
    "embedding_api_key": "OPENAI_API_KEY_EMBEDDING",
    "embedding_base_url": "OPENAI_BASE_URL_EMBEDDING",
    "embedding_model": "EMBEDDING_MODEL_NAME",
    "similarity_threshold": "SIMILARITY_THRESHOLD",
    "llm_timeout": "LLM_TIMEOUT",
}


def _sync_env_file(settings: dict):
    """将用户配置同步写入 .env 文件（保留注释和未管理变量，跳过空值）"""
    try:
        for profile_key, env_key in _ENV_KEY_MAP.items():
            if profile_key in settings:
                val = str(settings[profile_key]).strip()
                if val:  # 安全防护：绝不写入空值到 .env
                    set_key(ENV_PATH, env_key, val)
        logger.info("配置已同步到 .env 文件")
    except Exception as e:
        logger.warning(f"同步 .env 文件失败: {e}")
