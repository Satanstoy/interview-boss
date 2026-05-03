from app.asgi import app  # noqa: F401 — 导出 app 供 uvicorn main:app 使用

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.asgi:app", host="0.0.0.0", port=8000, reload=True)
