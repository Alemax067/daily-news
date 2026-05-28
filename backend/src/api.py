"""FastAPI service exposing extraction + chat endpoints."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from .agent import build_agent, build_chat_model
from .extractor import extract_detail, extract_list_only, extract_news
from .models import ChatRequest, ExtractRequest


_state: dict[str, Any] = {}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _state["checkpointer"] = InMemorySaver()
    _state["agent"] = build_agent().with_config(
        {"checkpointer": _state["checkpointer"]}
    )
    yield


app = FastAPI(title="daily-news agent", lifespan=_lifespan)


@app.post("/extract")
def extract_endpoint(req: ExtractRequest) -> dict[str, Any]:
    try:
        if req.with_detail:
            records = extract_news(
                req.url, req.section, with_detail=True, max_items=req.max_items
            )
            return {"count": len(records), "items": [r.model_dump() for r in records]}
        items = extract_list_only(req.url, req.section, max_items=req.max_items)
        return {"count": len(items), "items": [i.model_dump() for i in items]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/detail")
def detail_endpoint(url: str) -> dict[str, Any]:
    try:
        return extract_detail(url).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/chat")
def chat_endpoint(req: ChatRequest) -> dict[str, Any]:
    agent = _state.get("agent")
    if agent is None:
        raise HTTPException(status_code=503, detail="agent not initialized")
    session_id = req.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=req.message)]}, config=config
        )
        last = result["messages"][-1]
        return {
            "session_id": session_id,
            "reply": last.content if hasattr(last, "content") else str(last),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
