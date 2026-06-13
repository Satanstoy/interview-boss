"""Chat Agent Graph — 兼容层，委托给 pipeline.py。

原 LangGraph StateGraph 已替换为纯 async pipeline。
此文件保留兼容性导入：外部代码仍可 from app.agents.chat.graph import run_chat。
"""

from app.agents.chat.pipeline import run_chat

__all__ = ["run_chat"]
