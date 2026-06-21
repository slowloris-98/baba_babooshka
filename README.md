# Baba Babooshka

<p align="center">
  <img src="data/icon.png" alt="Baba Babooshka" width="320">
</p>

A [Fetch.ai uAgent](https://uagents.fetch.ai/) for all your discussions and project needs. Like the *babushka* — the wise grandmother who never forgets and the nesting doll with a whole world tucked inside — Baba Babooshka remembers every conversation and keeps the layers that matter close at hand.

Powered by **Claude Code**, she carries her own long-term **agent memory** so each chat picks up where the last one left off, and **Sentry** keeps watch over every session — so the conversations get sharper the more you talk, and nothing slips through the cracks.

## What it does

The agent accepts prompts from two sources:

| Source | Protocol | Use case |
|--------|----------|----------|
| ASI:One / Agentverse chat | Standard `chat_protocol` | Human users chatting via the Fetch.ai ecosystem |
| Another uAgent | `ClaudeRequest` → `ClaudeResponse` | Programmatic agent-to-agent calls |

Each request is enriched with **long-term memory**: before spawning Claude, the agent searches a [Redis Agent Memory Server](https://github.com/redis/agent-memory-server) for prior context from the same sender and prepends it to the prompt; after the run it persists the prompt + result back to memory. Memory is keyed per sender and can be disabled with `MEMORY_ENABLED=false`.

> **Safety:** the spawned Claude runs with `--dangerously-skip-permissions`, so it can read/edit files and run commands inside `CLAUDE_WORKDIR` autonomously. Point `CLAUDE_WORKDIR` at a dedicated/sandboxed folder, not your whole machine.

## Prerequisites

- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed and authenticated (`claude --version` should work)
- `uagents >= 0.22.0` (see [requirements.txt](requirements.txt))
- A running [Redis Agent Memory Server](https://github.com/redis/agent-memory-server) (optional — set `MEMORY_ENABLED=false` to skip)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

### Memory server

The agent stores long-term memory in a [Redis Agent Memory Server](https://github.com/redis/agent-memory-server). Run it in a separate terminal before starting the agent:

```bash
docker compose up api redis
```

The memory server's API defaults to port `8000`, which collides with `AGENT_PORT`. Run it on `8001` and point `MEMORY_SERVER_URL` at it (see the [Configuration](#configuration) table). To run the agent without memory, set `MEMORY_ENABLED=false`.

## Configuration

All settings are controlled by environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_SEED` | `baba-babooshka-seed-change-me` | Deterministic seed for the agent's identity. **Change this before deploying.** |
| `AGENT_NAME` | `baba_babooshka` | Human-readable name shown on Agentverse |
| `AGENT_PORT` | `8000` | Local HTTP port |
| `AGENTVERSE_API_KEY` | _(unset)_ | API key for the Agentverse mailbox (get one at [agentverse.ai](https://agentverse.ai)) |
| `CLAUDE_WORKDIR` | current working directory | Directory Claude Code runs in. All file edits happen here. |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Model passed to `claude --model`. Empty string = Claude's default. |
| `CLAUDE_TIMEOUT` | `600` | Seconds before a spawned Claude run is killed |
| `CLAUDE_MAX_TURNS` | `40` | Maximum agentic turns per Claude run |
| `MEMORY_ENABLED` | `true` | Set to `false` to disable long-term memory entirely |
| `MEMORY_SERVER_URL` | `http://localhost:8001` | Base URL of the Redis Agent Memory Server |

## Running

```bash
export AGENT_SEED="my-unique-secret-seed"
export AGENTVERSE_API_KEY="<your key>"
export CLAUDE_WORKDIR="/path/to/workspace"

python agent.py
```

On startup the agent logs its address:

```
INFO: Agent 'baba_babooshka' address: agent1q...
INFO: Claude binary: /usr/local/bin/claude
INFO: Claude workdir: /path/to/workspace
```

Copy that address to chat with it from ASI:One / Agentverse, or to message it from another agent.

## Agent-to-agent usage

```python
from uagents import Agent, Context, Model

class ClaudeRequest(Model):
    prompt: str

class ClaudeResponse(Model):
    result: str

WORKER = "agent1q..."  # address printed on worker startup

@agent.on_event("startup")
async def ask(ctx: Context):
    await ctx.send(WORKER, ClaudeRequest(prompt="List files in the workspace."))

@agent.on_message(model=ClaudeResponse)
async def got(ctx: Context, sender: str, msg: ClaudeResponse):
    print(msg.result)
```

## Running the test suite

[test_local.py](test_local.py) runs a full end-to-end test in a single process — it spins up the real worker alongside a throwaway client in a uAgents Bureau, sends a prompt, and checks the reply:

```bash
python test_local.py
```

Expected output on success:

```
TEST RESULT: worker replied -> 'PONG'
TEST PASSED
```

Times out after 90 seconds and exits with code 1 on failure.

## How it works

[`run_claude_code()`](agent.py) in [agent.py](agent.py) launches:

```
claude -p "<prompt>" --output-format json \
  --dangerously-skip-permissions --max-turns 40 --model claude-opus-4-8
```

via a non-blocking `asyncio` subprocess, parses the JSON `result` field, and returns the text. On any failure (missing binary, non-zero exit, timeout) it returns a human-readable error string so the agent stays alive.

When `MEMORY_ENABLED` is set, each incoming request is wrapped by two helpers in [agent.py](agent.py):

- [`get_memory_context()`](agent.py) searches long-term memory for the sender's prior interactions and prepends the top matches to the prompt.
- [`save_interaction()`](agent.py) persists a summary of the prompt + result as a semantic memory after the run.

Both fail soft — any memory-server error is reported to Sentry and the run continues without memory.

## Project layout

```
agent.py        — the worker agent
test_local.py   — local end-to-end test
requirements.txt
```

## License

MIT
