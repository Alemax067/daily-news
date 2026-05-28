"""Interactive REPL for chatting with the news-extraction agent."""

from __future__ import annotations

import sys
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from .agent import build_agent


def run_repl() -> None:
    print("daily-news agent (输入 :quit 退出, :reset 重置会话)")
    checkpointer = InMemorySaver()
    agent = build_agent().with_config({"checkpointer": checkpointer})
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    while True:
        try:
            user = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user:
            continue
        if user in {":quit", ":q", ":exit"}:
            return
        if user == ":reset":
            session_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": session_id}}
            print("(已重置会话)")
            continue

        try:
            result = agent.invoke(
                {"messages": [HumanMessage(content=user)]}, config=config
            )
            last = result["messages"][-1]
            text = last.content if hasattr(last, "content") else str(last)
            print(f"\n{text}")
        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
