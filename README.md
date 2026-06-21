# Claude Code Spawner — a Fetch.ai uAgent

A [uAgent](https://uagents.fetch.ai/docs/getting-started/create) that **spawns Claude Code**
on request. When you message it, it runs the `claude` CLI in headless mode
(`claude -p ...`) inside a configured working directory and replies with the result.

Two ways to talk to it:
- **Chat protocol** — chat with it from [ASI:One](https://asi1.ai) / Agentverse (it runs with a mailbox).
- **Direct messages** — another uAgent sends a `ClaudeRequest` and gets a `ClaudeResponse`.

> ⚠️ **Safety:** the spawned Claude runs with `--dangerously-skip-permissions`, so it can
> read/edit files and run commands **inside `CLAUDE_WORKDIR`** autonomously. Point
> `CLAUDE_WORKDIR` at a dedicated/sandboxed folder, not your whole machine.

## Prerequisites

- Python 3.10+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) installed and logged in
  (the agent reuses your existing Claude Code auth / `ANTHROPIC_API_KEY`). Verify with `claude --version`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell/cmd)
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

copy .env.example .env          # then edit .env (set AGENT_SEED + CLAUDE_WORKDIR)
```

Load `.env` into your shell before running (PowerShell example):

```powershell
Get-Content .env | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object {
  $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
```

## Run

```bash
python agent.py
```

On startup it logs the **agent address**, the resolved `claude` path, and the workdir:

```
INFO: Agent 'claude_code_spawner' address: agent1q...
INFO: Claude binary: C:\Users\you\.local\bin\claude
INFO: Claude workdir: d:/.../workspace
```

Copy the `agent1qd70krj4zhhwfy2n3u9rhxw3vsyv6v5rjp0wwctgechczqjyrxpnzcuhxrg` address to chat with it from ASI:One/Agentverse, or to message it
from another agent.

## Configuration (`.env`)

| Var | Default | Meaning |
| --- | --- | --- |
| `AGENT_SEED` | `claude-code-spawner-seed-change-me` | Secret seed → stable agent address. **Change it.** |
| `CLAUDE_WORKDIR` | current dir | Directory Claude Code runs in (sandbox this). |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Passed to `claude --model` (blank = Claude's default). |
| `CLAUDE_TIMEOUT` | `600` | Max seconds per spawned run before it's killed. |
| `CLAUDE_MAX_TURNS` | `40` | Max autonomous turns per run. |
| `AGENT_NAME` / `AGENT_PORT` | `claude_code_spawner` / `8000` | Agent identity / local port. |

## Test it locally (direct agent-to-agent)

With `agent.py` running, copy its printed address into `WORKER` below, then run this `client.py`:

```python
from uagents import Agent, Context, Model

WORKER = "agent1q..."  # <- paste the worker's address from its startup logs

class ClaudeRequest(Model):
    prompt: str

class ClaudeResponse(Model):
    result: str

client = Agent(name="client", seed="client-demo-seed", port=8001,
               endpoint=["http://localhost:8001/submit"])

@client.on_event("startup")
async def ask(ctx: Context):
    await ctx.send(WORKER, ClaudeRequest(
        prompt="Create hello.txt containing 'hi' and list the directory."))

@client.on_message(model=ClaudeResponse)
async def got(ctx: Context, sender: str, msg: ClaudeResponse):
    ctx.logger.info(f"Claude says:\n{msg.result}")

if __name__ == "__main__":
    client.run()
```

```bash
python client.py
```

Expect a logged reply and `hello.txt` appearing in `CLAUDE_WORKDIR`.

## How it works

`run_claude_code()` in [agent.py](agent.py) launches:

```
claude -p "<your request>" --output-format json \
  --dangerously-skip-permissions --max-turns 40 --model claude-opus-4-8
```

via a non-blocking `asyncio` subprocess (with a timeout), parses the JSON `result`, and sends it
back over the chat protocol or as a `ClaudeResponse`.
