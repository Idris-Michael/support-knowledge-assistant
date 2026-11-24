"""Chat models behind LangChain's `BaseChatModel`, so the graph does not care which one runs.

- `ClaudeCliChat`: Claude through `claude -p` (a subscription, no API key), with tools, MCP servers,
  slash commands and user settings switched off so the model sees only the prompt.
- `ProxyChat`: the same model through `ska-llm-proxy`, for containers that do not hold the login.
- `OfflineChat`: deterministic rules shaped like the real output, for tests and credential-free runs.
  Any benchmark run that used it says so.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from typing import Any

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from .config import Settings


class LLMError(Exception):
    pass


def split_messages(messages: list[BaseMessage]) -> tuple[str, str]:
    system = "\n\n".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
    prompt = "\n\n".join(str(m.content) for m in messages if not isinstance(m, SystemMessage))
    return system, prompt


def _result(text: str, model: str, latency_ms: int, tokens_in: int = 0, tokens_out: int = 0) -> ChatResult:
    msg = AIMessage(
        content=text,
        response_metadata={"model": model, "latency_ms": latency_ms},
        usage_metadata={
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    )
    return ChatResult(generations=[ChatGeneration(message=msg)])


class ClaudeCliChat(BaseChatModel):
    model: str
    binary: str | None = None
    timeout_s: float = 180.0

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        found = self.binary or shutil.which("claude")
        if not found:
            raise LLMError("claude CLI not found on PATH (set CLAUDE_CLI_PATH or LLM_MODE=offline)")
        system, prompt = split_messages(messages)
        # argv is a list and the prompt goes on stdin: question text never reaches a shell.
        args = [
            found, "-p", "--model", self.model, "--output-format", "json", "--tools", "",
            "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "",
            "--no-session-persistence", "--system-prompt", system,
        ]  # fmt: skip
        started = time.perf_counter()
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, binary resolved from PATH
                args, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=self.timeout_s
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude-cli timed out after {self.timeout_s}s") from e
        latency = int((time.perf_counter() - started) * 1000)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"unreadable claude-cli output: {(proc.stdout or proc.stderr)[:160]}") from e
        if data.get("is_error"):
            raise LLMError(f"claude-cli error: {str(data.get('result'))[:200]}")
        usage = data.get("usage") or {}
        tokens_in = sum(
            int(usage.get(k, 0))
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        return _result(
            str(data.get("result", "")), self.model, latency, tokens_in, int(usage.get("output_tokens", 0))
        )


class ProxyChat(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str
    base_url: str
    token: str
    transport: httpx.BaseTransport | None = None
    _http: httpx.Client | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "ska-llm-proxy"

    def _client(self) -> httpx.Client:
        if self._http is None:  # one client, reused: a new one per call costs a TLS/TCP setup each time
            self._http = httpx.Client(
                base_url=self.base_url,
                transport=self.transport,
                timeout=200.0,
                headers={"authorization": f"Bearer {self.token}"},
            )
        return self._http

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, prompt = split_messages(messages)
        try:
            res = self._client().post(
                "/v1/complete", json={"system": system, "prompt": prompt, "model": self.model}
            )
        except httpx.HTTPError as e:
            raise LLMError(f"llm proxy unreachable: {e}") from e
        if res.status_code != 200:
            raise LLMError(f"llm proxy {res.status_code}: {res.text[:200]}")
        d = res.json()
        return _result(
            d["text"], d["model"], d["latency_ms"], d.get("input_tokens", 0), d.get("output_tokens", 0)
        )


# ------------------------------------------------------------------ offline stand-in

SOURCE = re.compile(r'<source n="(\d+)"[^>]*>(.*?)</source>', re.S)
STOP = set(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "is",
        "it",
        "do",
        "does",
        "how",
        "what",
        "we",
        "our",
        "i",
        "my",
        "can",
        "for",
        "on",
        "with",
        "that",
        "this",
        "be",
        "are",
        "why",
        "which",
        "when",
        "there",
    ]
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]{3,}", text.lower()) if w not in STOP}


class OfflineChat(BaseChatModel):
    """Grades a source relevant when it shares at least two content words with the question, and
    answers with the first sentence of each relevant source, cited. Good enough to exercise every
    branch of the graph; not a measure of answer quality."""

    model: str = "offline"

    @property
    def _llm_type(self) -> str:
        return "offline"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, prompt = split_messages(messages)
        question = re.search(r"<question>(.*?)</question>", prompt, re.S)
        q = _words(question.group(1) if question else "")
        sources = [(int(n), body) for n, body in SOURCE.findall(prompt)]
        relevant = [n for n, body in sources if len(q & _words(body)) >= 2]
        if "GRADE" in system:
            return _result(json.dumps({"relevant": relevant}), "offline", 1)
        if not relevant:
            return _result("NOT_IN_SOURCES", "offline", 1)
        parts = []
        for n, body in sources:
            if n in relevant:
                first = re.split(r"(?<=[.!?])\s", body.strip(), maxsplit=1)[0]
                parts.append(f"{first} [{n}]")
        return _result(" ".join(parts[:2]), "offline", 1)


def make_chat(settings: Settings, model: str) -> BaseChatModel:
    if settings.llm_mode == "offline":
        return OfflineChat()
    if settings.llm_mode == "proxy":
        if settings.llm_proxy_token is None:
            raise LLMError("LLM_MODE=proxy needs LLM_PROXY_TOKEN")
        return ProxyChat(
            model=model, base_url=settings.llm_proxy_url, token=settings.llm_proxy_token.get_secret_value()
        )
    return ClaudeCliChat(model=model, binary=settings.claude_cli_path)
