import os
import logging
from urllib.parse import quote, urlsplit, urlunsplit
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


_RUNTIME_SECRET_MIN_LENGTHS = {
    "ADMIN_PASSWORD": 16,
    "JWT_SECRET": 32,
    "OAUTH_SECRET_KEY": 32,
}


def validate_runtime_secrets(values: dict[str, str] | None = None) -> None:
    """Reject weak production credentials before database initialization.

    ``values`` is injectable for deterministic tests.  Non-production test and
    development processes keep their existing placeholder setup, while the
    production Docker profile must provide all configured secrets explicitly.
    """
    env = os.environ if values is None else values
    if str(env.get("ENV", "")).strip().lower() not in {"production", "prod"}:
        return

    for name, minimum_length in _RUNTIME_SECRET_MIN_LENGTHS.items():
        value = str(env.get(name, ""))
        if len(value) < minimum_length:
            raise RuntimeError(
                f"{name} must be at least {minimum_length} characters in production"
            )


LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "gpt-4o")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024  # 默认 10MB
MAX_TOTAL_UPLOAD_SIZE = (
    int(os.environ.get("MAX_TOTAL_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
)  # 默认 50MB

LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")

def _read_secret_file() -> str:
    path = os.environ.get("REDIS_PASSWORD_FILE", "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    except OSError:
        return ""


REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "").strip() or _read_secret_file()


def build_redis_url(raw_url: str | None, default_url: str) -> str:
    """Add the runtime Redis password while preserving legacy DSN overrides."""

    value = (raw_url or default_url).strip()
    if not REDIS_PASSWORD:
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"redis", "rediss"} or parsed.username or parsed.password:
        return value
    if not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f":{quote(REDIS_PASSWORD, safe='')}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def redact_redis_url(value: str) -> str:
    """Return a log-safe Redis DSN."""

    parsed = urlsplit(value)
    if not parsed.password:
        return value
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{parsed.username or ''}:***@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


# Redis 配置。REDIS_URL 保留为兼容旧部署配置的别名；新的 Docker 部署
# 通过 REDIS_HOST/REDIS_CACHE_HOST + Docker secret 组装带认证的 DSN。
REDIS_QUEUE_URL = build_redis_url(
    os.environ.get("REDIS_QUEUE_URL") or os.environ.get("REDIS_URL"),
    f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:6379/0",
)
REDIS_URL = REDIS_QUEUE_URL
REDIS_CACHE_URL = build_redis_url(
    os.environ.get("REDIS_CACHE_URL"),
    f"redis://{os.environ.get('REDIS_CACHE_HOST', 'localhost')}:6379/0",
)
MASTER_BANK_CACHE_TTL_SECONDS = max(
    1, int(os.environ.get("MASTER_BANK_CACHE_TTL_SECONDS", "15"))
)
MASTER_BANK_CACHE_MAX_BYTES = max(
    64 * 1024,
    int(os.environ.get("MASTER_BANK_CACHE_MAX_BYTES", str(1024 * 1024))),
)

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
        from app.services.encryption import decrypt_value

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT api_key, base_url, model, timeout, api_format, thinking FROM user_llm_config WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row:
                cfg = dict(row)
                # Decrypt the stored API key
                if cfg.get("api_key"):
                    cfg["api_key"] = decrypt_value(cfg["api_key"])
                # 未配置 api_key 视为未配置，回退到全局
                if not cfg.get("api_key"):
                    return _get_global_llm_config()
                return cfg
    except Exception:
        pass
    return _get_global_llm_config()


def _read_public_search_config_from_db() -> dict | None:
    """Read the administrator-managed public search config from user_profile."""
    try:
        from app.db.connection import get_db_connection
        from app.services.encryption import decrypt_value

        keys = (
            "search_provider",
            "search_api_key",
            "search_base_url",
            "search_enabled",
        )
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_profile WHERE key IN ({})".format(
                    ",".join("?" * len(keys))
                ),
                keys,
            ).fetchall()
        values = {row["key"]: row["value"] for row in rows}
    except Exception:
        return None

    provider = (values.get("search_provider") or "").strip().lower()
    api_key = decrypt_value((values.get("search_api_key") or "").strip())
    enabled = values.get("search_enabled")
    if enabled == "0":
        return {"provider": "none", "api_key": "", "base_url": "", "source": "disabled"}
    if provider == "none" or not api_key:
        return None
    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": (values.get("search_base_url") or "").strip(),
        "enabled": 1,
        "source": "admin",
    }


def get_public_search_config() -> dict | None:
    """Resolve the public search config, preferring admin DB settings over env."""
    stored = _read_public_search_config_from_db()
    if stored is not None:
        return stored if stored.get("provider") != "none" else None

    provider = os.environ.get("SEARCH_PROVIDER", "none").strip().lower()
    api_key = os.environ.get("SEARCH_API_KEY", "").strip()
    if provider == "none" or not api_key:
        return None
    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": os.environ.get("SEARCH_BASE_URL", "").strip(),
        "enabled": 1,
        "source": "environment",
    }


def get_user_search_config_status(
    user_id: int | None, scope: str = "user"
) -> dict:
    """Resolve search availability without exposing any API key.

    Public answer generation uses the administrator-managed public search
    configuration and must not be affected by a user's personal provider.
    """
    if scope == "public":
        public = get_public_search_config()
        return {
            "configured": bool(public),
            "source": "public" if public else "none",
            "personal_configured": False,
            "public_configured": bool(public),
            "is_admin": True,
        }

    if user_id is None:
        return {
            "configured": False,
            "source": "none",
            "personal_configured": False,
            "public_configured": False,
            "is_admin": False,
        }

    try:
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT u.is_admin, usc.provider, usc.api_key, usc.enabled "
                "FROM users u LEFT JOIN user_search_config usc ON usc.user_id = u.id "
                "WHERE u.id = ?",
                (user_id,),
            ).fetchone()
    except Exception:
        row = None

    if not row:
        return {
            "configured": False,
            "source": "none",
            "personal_configured": False,
            "public_configured": False,
            "is_admin": False,
        }

    personal_configured = bool(
        row["enabled"]
        and row["provider"]
        and row["provider"] != "none"
        and row["api_key"]
    )
    is_admin = bool(row["is_admin"])
    public_configured = bool(get_public_search_config()) if is_admin else False
    if personal_configured:
        source = "personal"
    elif public_configured:
        source = "public"
    else:
        source = "none"
    return {
        "configured": personal_configured or public_configured,
        "source": source,
        "personal_configured": personal_configured,
        "public_configured": public_configured,
        "is_admin": is_admin,
    }


def get_user_search_config(user_id: int | None, scope: str = "user") -> dict | None:
    """Resolve search config for an explicit task scope."""
    try:
        from app.db.connection import get_db_connection
        from app.services.encryption import decrypt_value

        if scope == "public":
            return get_public_search_config()

        if user_id is None:
            return None
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT u.is_admin, usc.provider, usc.api_key, usc.base_url, usc.enabled "
                "FROM users u LEFT JOIN user_search_config usc ON usc.user_id = u.id "
                "WHERE u.id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None

        if (
            row["enabled"]
            and row["provider"]
            and row["provider"] != "none"
            and row["api_key"]
        ):
            return {
                "provider": row["provider"],
                "api_key": decrypt_value(row["api_key"]),
                "base_url": row["base_url"] or "",
                "enabled": row["enabled"],
                "source": "personal",
            }

        if row["is_admin"]:
            public = get_public_search_config()
            if public:
                return public
    except Exception:
        pass
    return None


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
