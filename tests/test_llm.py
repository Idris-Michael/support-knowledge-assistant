from __future__ import annotations

import json
import subprocess
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from support_knowledge_assistant import llm
from support_knowledge_assistant.config import Settings


def run_returning(stdout: str, calls: list[dict[str, Any]] | None = None) -> Any:
    def fake_run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append({"args": args, **kw})
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    return fake_run


def test_claude_cli_sends_prompt_on_stdin_with_tools_off(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    out = json.dumps(
        {"result": "hi [1]", "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 3}}
    )
    monkeypatch.setattr(subprocess, "run", run_returning(out, calls))
    chat = llm.ClaudeCliChat(model="claude-haiku-5-5", binary="claude")
    reply = chat.invoke([SystemMessage("SYS"), HumanMessage("question; rm -rf /")])
    assert reply.content == "hi [1]"
    assert reply.usage_metadata == {"input_tokens": 15, "output_tokens": 3, "total_tokens": 18}
    args = calls[0]["args"]
    assert args[:4] == ["claude", "-p", "--model", "claude-haiku-5-5"]
    assert args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args
    assert args[-1] == "SYS" and calls[0]["input"] == "question; rm -rf /"


@pytest.mark.parametrize(
    ("stdout", "match"),
    [("not json", "unreadable"), (json.dumps({"is_error": True, "result": "quota"}), "quota")],
)
def test_claude_cli_errors_are_loud(monkeypatch: pytest.MonkeyPatch, stdout: str, match: str) -> None:
    monkeypatch.setattr(subprocess, "run", run_returning(stdout))
    with pytest.raises(llm.LLMError, match=match):
        llm.ClaudeCliChat(model="m", binary="claude").invoke("x")


def test_claude_cli_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*a: Any, **k: Any) -> None:
        raise subprocess.TimeoutExpired("claude", 1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(llm.LLMError, match="timed out"):
        llm.ClaudeCliChat(model="m", binary="claude", timeout_s=1).invoke("x")


def test_claude_cli_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda _: None)
    with pytest.raises(llm.LLMError, match="not found"):
        llm.ClaudeCliChat(model="m").invoke("x")


def test_proxy_chat_round_trip_and_errors() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        body = json.loads(req.content)
        if body["model"] == "bad":
            return httpx.Response(400, text="model not allowed")
        return httpx.Response(200, json={"text": "ok [1]", "model": body["model"], "latency_ms": 5})

    t = httpx.MockTransport(handler)
    chat = llm.ProxyChat(model="claude-sonnet-5-5", base_url="http://proxy", token="t" * 24, transport=t)
    assert chat.invoke([SystemMessage("S"), HumanMessage("Q")]).content == "ok [1]"
    assert seen[0].headers["authorization"] == "Bearer " + "t" * 24
    assert json.loads(seen[0].content) == {"system": "S", "prompt": "Q", "model": "claude-sonnet-5-5"}
    with pytest.raises(llm.LLMError, match="400"):
        llm.ProxyChat(model="bad", base_url="http://proxy", token="t" * 24, transport=t).invoke("x")


def test_proxy_unreachable() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    chat = llm.ProxyChat(
        model="m", base_url="http://proxy", token="t" * 24, transport=httpx.MockTransport(boom)
    )
    with pytest.raises(llm.LLMError, match="unreachable"):
        chat.invoke("x")


def test_offline_chat_grades_and_answers_with_citations() -> None:
    prompt = (
        "<question>why does vacuum not shrink the table</question>\n\n"
        '<source n="1" section="a">Vacuum marks table space for reuse. More text.</source>\n\n'
        '<source n="2" section="b">Unrelated words entirely.</source>'
    )
    chat = llm.OfflineChat()
    assert json.loads(str(chat.invoke([SystemMessage("GRADE"), HumanMessage(prompt)]).content)) == {
        "relevant": [1]
    }
    assert (
        chat.invoke([SystemMessage("answer"), HumanMessage(prompt)]).content
        == "Vacuum marks table space for reuse. [1]"
    )
    empty = "<question>zzz qqq</question>\n\n" + prompt.split("\n\n", 1)[1]
    assert chat.invoke([SystemMessage("answer"), HumanMessage(empty)]).content == "NOT_IN_SOURCES"


def test_make_chat_picks_by_mode() -> None:
    assert isinstance(llm.make_chat(Settings(llm_mode="offline"), "m"), llm.OfflineChat)
    assert isinstance(llm.make_chat(Settings(llm_mode="claude-cli"), "m"), llm.ClaudeCliChat)
    proxy = Settings(llm_mode="proxy", llm_proxy_token="p" * 24)  # type: ignore[arg-type]
    assert isinstance(llm.make_chat(proxy, "m"), llm.ProxyChat)
    with pytest.raises(llm.LLMError, match="LLM_PROXY_TOKEN"):
        llm.make_chat(Settings(llm_mode="proxy"), "m")
