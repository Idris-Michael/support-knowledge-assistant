# 5. Claude through a LangChain chat model, with a proxy and an offline stand-in

Status: accepted

## Context
The pilot has no API budget. Claude is available on this machine through `claude -p` (a
subscription), and must also be reachable from containers. CI and a fresh clone must run with no
model and no credentials at all.

## Decision
Three `BaseChatModel` implementations behind `LLM_MODE`, so the graph only ever sees LangChain's
interface:

- `claude-cli`: `claude -p` with tools, MCP servers, slash commands and user settings turned off, so
  the model sees only the prompt. Arguments are a fixed list and the prompt goes on stdin; question
  text never reaches a shell.
- `proxy`: the same through `ska-llm-proxy` on the host (token-protected, only the configured grade
  and answer models). Containers use this.
- `offline`: deterministic keyword rules shaped like the real output. Exercises every branch of the
  graph; says nothing about answer quality.

## Consequences
- In a client deployment `LLM_PROXY_URL` points at the client's model gateway (for example in front
  of Claude on Amazon Bedrock or Azure AI Foundry). This repo has no Bedrock or Azure chat adapter.
- `claude -p` starts a process for every call; the latencies in the README include that overhead
  (not measured separately).
- Token counts come from the CLI's usage report and include cached input.
- Every benchmark result records which mode produced it.
