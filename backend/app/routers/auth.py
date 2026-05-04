import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.core.auth import hash_password, verify_password, create_access_token, get_current_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("multimodal-parser")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class BankModeRequest(BaseModel):
    bank_mode: str  # 'public' / 'personal' / 'mixed'


@router.post("/register")
async def register(req: RegisterRequest):
    if len(req.username) < 2 or len(req.username) > 32:
        raise HTTPException(status_code=400, detail="用户名长度需在 2-32 之间")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")

    password_hash = hash_password(req.password)

    def _create():
        with get_db_connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (req.username,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="用户名已存在")
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, 0, 'public')",
                (req.username, password_hash)
            )
            conn.commit()
            return cursor.lastrowid

    try:
        user_id = await run_db(_create)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("注册失败")
        raise HTTPException(status_code=500, detail="注册失败")

    token = create_access_token({"user_id": user_id, "username": req.username})
    return {"token": token, "user": {"id": user_id, "username": req.username, "is_admin": False, "bank_mode": "public"}}


@router.post("/login")
async def login(req: LoginRequest):
    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash, is_admin, bank_mode FROM users WHERE username = ?",
                (req.username,)
            ).fetchone()

    user = await run_db(_query)
    if not user or not verify_password(req.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token({"user_id": user['id'], "username": user['username']})
    return {
        "token": token,
        "user": {
            "id": user['id'],
            "username": user['username'],
            "is_admin": bool(user['is_admin']),
            "bank_mode": user['bank_mode'] or 'public'
        }
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.put("/bank-mode")
async def update_bank_mode(req: BankModeRequest, current_user: dict = Depends(get_current_user)):
    if req.bank_mode not in ('public', 'personal', 'mixed'):
        raise HTTPException(status_code=400, detail="无效的题库模式，可选: public / personal / mixed")

    def _update():
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET bank_mode = ? WHERE id = ?", (req.bank_mode, current_user['id']))
            conn.commit()

    await run_db(_update)
    return {"status": "success", "bank_mode": req.bank_mode}
