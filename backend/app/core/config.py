import os
import logging
from dotenv import load_dotenv, set_key

load_dotenv()

logger = logging.getLogger("interview-boss")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "interview-boss.db")
ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
)

LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "gpt-4o")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024  # 默认 10MB
MAX_TOTAL_UPLOAD_SIZE = (
    int(os.environ.get("MAX_TOTAL_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
)  # 默认 50MB

LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")

# Redis 配置（ARQ 任务队列）
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# ── 聚类参数（env 可覆盖，启动加载，非热更新）─────────────────
CLUSTER_BATCH_SIZE = int(os.environ.get("CLUSTER_BATCH_SIZE", "40"))
CLUSTER_MAX_CONCURRENCY = int(os.environ.get("CLUSTER_MAX_CONCURRENCY", "8"))
CLUSTER_PREFILTER_TOP_K = int(os.environ.get("CLUSTER_PREFILTER_TOP_K", "30"))
CLUSTER_RECENT_DAYS = int(os.environ.get("CLUSTER_RECENT_DAYS", "7"))
CLUSTER_VALIDATION_BATCH = int(os.environ.get("CLUSTER_VALIDATION_BATCH", "20"))
CLUSTER_DIRECT_ACCEPT = float(os.environ.get("CLUSTER_DIRECT_ACCEPT_CONF", "0.92"))
CLUSTER_VALIDATION_ACCEPT = float(os.environ.get("CLUSTER_VALIDATION_ACCEPT", "0.8"))
CLUSTER_MIN_SIMILARITY = float(os.environ.get("CLUSTER_MIN_SIMILARITY", "0.6"))
CLUSTER_V2_SIM_THRESHOLD = float(os.environ.get("CLUSTER_V2_SIM_THRESHOLD", "0.6"))
CLUSTER_V2_FAISS_TOP_K = int(os.environ.get("CLUSTER_V2_FAISS_TOP_K", "10"))
CLUSTER_COMPACTION_CONCURRENCY = int(
    os.environ.get("CLUSTER_COMPACTION_CONCURRENCY", "8")
)
CLUSTER_CAT2_BATCH = int(os.environ.get("CLUSTER_CAT2_BATCH", "5"))
CLUSTER_PHASE2_BATCH = int(os.environ.get("CLUSTER_PHASE2_BATCH", "20"))


# 字段白名单（用于 GenericUpdateRequest 安全校验）
ALLOWED_UPDATE_COLUMNS = {
    "master_question_bank": {
        "question",
        "cat1",
        "cat2",
        "tags",
        "difficulty",
        "ai_answer",
        "is_starred",
    },
    "question_bank": {
        "question",
        "cat1",
        "cat2",
        "tags",
        "difficulty",
        "ai_answer",
        "original_questions",
        "original_question_sources",
    },
    "jd": {"url", "company", "job_title", "salary", "tech_stack", "bonus"},
    "interview": {
        "url",
        "company",
        "round",
        "focus",
        "questions_list",
        "difficulty",
        "season",
    },
    "questions_detail": {
        "url",
        "company",
        "round",
        "question",
        "cat1",
        "cat2",
        "tags",
        "diff_tag",
    },
}


def get_profile_setting(key: str, default: str = "") -> str:
    """从 user_profile 表读取配置值（复用线程级连接）"""
    try:
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT value FROM user_profile WHERE key = ?", (key,)
            ).fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return default


def get_user_llm_config(user_id: int) -> dict | None:
    """从 user_llm_config 表读取用户的 LLM 配置。未配置时回退到全局配置。"""
    try:
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT api_key, base_url, model, timeout FROM user_llm_config WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row:
                cfg = dict(row)
                # 未配置 api_key 视为未配置，回退到全局
                if not cfg.get("api_key"):
                    return _get_global_llm_config()
                return cfg
    except Exception:
        pass
    return _get_global_llm_config()


def get_user_search_config(user_id: int | None) -> dict | None:
    """读取用户的联网搜索配置，未配置时回退到可选的全局环境配置。"""
    try:
        from app.db.connection import get_db_connection

        if user_id is not None:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT provider, api_key, base_url, enabled "
                    "FROM user_search_config WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            if row:
                cfg = dict(row)
                if cfg.get("enabled") and cfg.get("provider") != "none" and cfg.get("api_key"):
                    return cfg
                return None
    except Exception:
        pass

    provider = os.environ.get("SEARCH_PROVIDER", "none").strip().lower()
    api_key = os.environ.get("SEARCH_API_KEY", "").strip()
    if provider == "none" or not api_key:
        return None
    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": os.environ.get("SEARCH_BASE_URL", "").strip(),
        "enabled": 1,
    }


def _get_global_llm_config() -> dict | None:
    """获取全局 LLM 配置（环境变量 + user_profile 表）。无配置时返回 None。"""
    api_key = (
        get_profile_setting("llm_api_key")
        or LLM_API_KEY
        or os.environ.get("OPENAI_API_KEY", "")
    )
    base_url = get_profile_setting("llm_base_url") or LLM_BASE_URL
    model = get_profile_setting("llm_model") or LLM_MODEL
    timeout_str = get_profile_setting("llm_timeout")

    if not api_key:
        return None

    timeout = LLM_TIMEOUT
    if timeout_str:
        try:
            timeout = max(5, min(int(timeout_str), 600))
        except ValueError:
            pass

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": timeout,
    }


def _reload_from_db():
    """从数据库加载用户配置，覆盖模块级常量（启动时 + 配置更新后调用）"""
    global LLM_MODEL, LLM_TIMEOUT
    global LLM_API_KEY, LLM_BASE_URL

    db_llm = get_profile_setting("llm_model")
    db_llm_key = get_profile_setting("llm_api_key")
    db_llm_url = get_profile_setting("llm_base_url")
    db_timeout = get_profile_setting("llm_timeout")

    if db_llm:
        LLM_MODEL = db_llm
    if db_timeout:
        try:
            val = int(db_timeout)
            # B10: 超时范围验证，防止极端值
            LLM_TIMEOUT = max(5, min(val, 600))
        except ValueError:
            pass
    if db_llm_key:
        LLM_API_KEY = db_llm_key
    if db_llm_url:
        LLM_BASE_URL = db_llm_url

    logger.info(f"配置已加载: LLM_MODEL={LLM_MODEL}, LLM_TIMEOUT={LLM_TIMEOUT}")

    # 重建 LLM 客户端
    try:
        from app.services.llm import rebuild_clients

        rebuild_clients()
    except Exception as e:
        logger.error(f"重建 LLM 客户端失败: {e}", exc_info=True)


# user_profile key → .env 变量名的映射
_ENV_KEY_MAP = {
    "llm_api_key": "OPENAI_API_KEY",
    "llm_base_url": "OPENAI_BASE_URL",
    "llm_model": "LLM_MODEL_NAME",
    "llm_timeout": "LLM_TIMEOUT",
}


def _sync_env_file(settings: dict):
    """将非敏感配置同步写入 .env 文件（LLM 密钥等敏感字段已迁移到 per-user 存储，不再同步）"""
    try:
        for profile_key, env_key in _ENV_KEY_MAP.items():
            # 跳过 LLM 敏感字段 — 已迁移到 user_llm_config 表
            if profile_key in (
                "llm_api_key",
                "llm_base_url",
                "llm_model",
                "llm_timeout",
            ):
                continue
            if profile_key in settings:
                val = str(settings[profile_key]).strip()
                if val:  # 安全防护：绝不写入空值到 .env
                    val = val.replace("\n", "").replace("\r", "").replace("\0", "")
                    set_key(ENV_PATH, env_key, val)
        logger.info("配置已同步到 .env 文件")
    except Exception as e:
        logger.warning(f"同步 .env 文件失败: {e}")
