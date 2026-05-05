from app.asgi import app  # noqa: F401 — 导出 app 供 uvicorn main:app 使用

import os
import uvicorn

if __name__ == "__main__":
    debug = os.getenv("DEBUG", "false").lower() == "true"
    uvicorn.run("app.asgi:app", host="0.0.0.0", port=8000, reload=debug)
