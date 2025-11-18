import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

fake_langchain_openai = types.ModuleType("langchain_openai")


class _DummyChatOpenAI:
    def __init__(self, *_, **__):
        pass

    def invoke(self, *_args, **_kwargs):
        raise AssertionError("ChatOpenAI should be mocked in tests")


fake_langchain_openai.ChatOpenAI = _DummyChatOpenAI
sys.modules.setdefault("langchain_openai", fake_langchain_openai)

from app.langgraph.nodes import context_assembler


def test_assemble_updates_summary(monkeypatch):
    calls = {"count": 0}

    def fake_summarize(old_summary, messages):
        calls["count"] += 1
        assert old_summary == "prev summary"
        assert messages == state_messages
        return "new summary"

    state_messages = [
        {"role": "user", "content": "안녕하세요"},
        {"role": "assistant", "content": "무엇을 도와드릴까요?"},
    ]

    state = {
        "messages": state_messages.copy(),
        "rolling_summary": "prev summary",
        "turn_count": 30,
        "retrieval": {
            "profile_ctx": {"name": "홍길동"},
            "collection_ctx": {"source": "knowledge-base"},
            "rag_snippets": [{"id": "doc-1", "content": "문서 발췌"}],
        },
    }

    monkeypatch.setattr(context_assembler, "_summarize", fake_summarize)

    result = context_assembler.assemble(state)

    assert calls["count"] == 1
    assert result["rolling_summary"] == "new summary"
    assert len(result["messages"]) == len(state_messages) + 1

    tool_message = result["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["content"] == "[context_assembler] prompt_ready"
    assert "created_at" in tool_message

    meta = tool_message["meta"]
    assert meta["summary_updated"] is True
    assert meta["turn_count"] == 30

    # assemble는 retrieval 정보를 직접 meta에 넣지 않지만,
    # rolling_summary 업데이트 결과가 반영되었는지 확인한다.
    assert result["rolling_summary"] == "new summary"


def test_assemble_keeps_summary_when_not_due(monkeypatch):
    def fail_summarize(*_):
        raise AssertionError("Should not update summary on non-15th turn")

    monkeypatch.setattr(context_assembler, "_summarize", fail_summarize)

    state = {
        "messages": [{"role": "user", "content": "테스트"}],
        "rolling_summary": "existing summary",
        "turn_count": 14,
        "retrieval": {},
    }

    result = context_assembler.assemble(state)

    assert result["rolling_summary"] == "existing summary"
    assert len(result["messages"]) == 2

    tool_message = result["messages"][-1]
    assert tool_message["meta"]["summary_updated"] is False
    assert tool_message["meta"]["turn_count"] == 14
    assert result["rolling_summary"] == "existing summary"

