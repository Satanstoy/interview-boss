import os
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = "/root/sj/multimodal-parser/backend/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "multimodal.db")

LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "gpt-4o")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.85"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024  # 默认 10MB

# 字段白名单（用于 GenericUpdateRequest 安全校验）
ALLOWED_UPDATE_COLUMNS = {
    "master_question_bank": {"question", "cat1", "cat2", "tags", "difficulty", "ai_answer", "is_starred"},
    "jd": {"url", "company", "job_title", "salary", "tech_stack", "bonus"},
    "interview": {"url", "company", "round", "focus", "questions_list", "difficulty"},
    "questions_detail": {"url", "company", "round", "question", "cat1", "cat2", "tags", "diff_tag"},
}
