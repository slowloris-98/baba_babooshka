"""A Fetch.ai uAgent that spawns Claude Code (the `claude` CLI) on a user's request.

When the agent receives a message (via the standard chat protocol from ASI:One /
Agentverse, or via a direct ClaudeRequest from another agent), it runs Claude Code
in headless mode (`claude -p ...`) inside CLAUDE_WORKDIR and returns the result.

See: https://uagents.fetch.ai/docs/getting-started/create
"""

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

import sentry_sdk

from uagents import Agent, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment / .env)
# ---------------------------------------------------------------------------
AGENT_SEED = os.environ.get("AGENT_SEED", "baba-babooshka-seed-change-me")
AGENT_NAME = os.environ.get("AGENT_NAME", "Baba Babooshka")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8000"))

# Directory Claude Code runs in. Defaults to the current working directory.
CLAUDE_WORKDIR = os.environ.get("CLAUDE_WORKDIR", os.getcwd())
# Model passed to `claude --model`. Empty string -> let claude use its default.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
# Hard cap on how long a single spawned Claude run may take (seconds).
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
# Bound on autonomous agentic turns for a single run.
CLAUDE_MAX_TURNS = int(os.environ.get("CLAUDE_MAX_TURNS", "40"))


def _resolve_claude() -> str | None:
    """Locate the claude executable, handling the Windows .cmd/.exe shims."""
    for candidate in ("claude", "claude.cmd", "claude.exe"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


CLAUDE_BIN = _resolve_claude()

# ---------------------------------------------------------------------------
# Sentry — initialize before any agent/framework code
# ---------------------------------------------------------------------------
_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=1.0,
        enable_logs=True,
    )


async def run_claude_code(prompt: str, logger=None) -> str:
    """Spawn Claude Code headlessly to handle `prompt`; return its text result.

    Never raises: on any failure it returns a human-readable error string so the
    agent stays alive and the caller gets useful feedback.
    """
    if CLAUDE_BIN is None:
        return (
            "Error: the `claude` CLI was not found on PATH. Install Claude Code "
            "and make sure `claude` is runnable, then restart the agent."
        )

    args = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--max-turns",
        str(CLAUDE_MAX_TURNS),
    ]
    if CLAUDE_MODEL:
        args += ["--model", CLAUDE_MODEL]

    if logger:
        logger.info(f"Spawning Claude Code in {CLAUDE_WORKDIR}: {prompt[:120]!r}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=CLAUDE_WORKDIR,
            env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        sentry_sdk.capture_exception(exc)
        return f"Error: failed to start Claude Code: {exc}"

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=CLAUDE_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        with sentry_sdk.new_scope() as scope:
            scope.set_extra("prompt_preview", prompt[:300])
            scope.set_extra("timeout_seconds", CLAUDE_TIMEOUT)
            scope.set_extra("workdir", CLAUDE_WORKDIR)
            sentry_sdk.capture_message(
                f"Claude Code timed out after {CLAUDE_TIMEOUT}s",
                level="error",
            )
        return (
            f"Error: Claude Code timed out after {CLAUDE_TIMEOUT}s and was stopped. "
            "Try a smaller task or raise CLAUDE_TIMEOUT."
        )

    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        detail = stderr or stdout or "(no output)"
        with sentry_sdk.new_scope() as scope:
            scope.set_extra("exit_code", proc.returncode)
            scope.set_extra("stderr", stderr[:2000])
            scope.set_extra("stdout", stdout[:2000])
            scope.set_extra("prompt_preview", prompt[:300])
            scope.set_extra("workdir", CLAUDE_WORKDIR)
            sentry_sdk.capture_message(
                f"Claude Code exited with code {proc.returncode}",
                level="error",
            )
        return f"Error: Claude Code exited with code {proc.returncode}.\n{detail}"

    # `--output-format json` prints a single JSON object with a `result` field.
    try:
        payload = json.loads(stdout)
        if isinstance(payload, dict) and "result" in payload:
            return str(payload["result"]).strip() or "(Claude returned an empty result.)"
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back to raw output if the shape is unexpected.
    return stdout or stderr or "(Claude Code produced no output.)"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
_agentverse_key = os.environ.get("AGENTVERSE_API_KEY", "")
agent = Agent(
    name=AGENT_NAME,
    seed=AGENT_SEED,
    port=AGENT_PORT,
    # Pass the API key if set, otherwise fall back to uagents' own env-var lookup.
    mailbox=_agentverse_key if _agentverse_key else True,
    publish_agent_details=True,
    readme_path = "README.md"
)


@agent.on_event("startup")
async def on_startup(ctx: Context):
    ctx.logger.info(f"Agent '{agent.name}' address: {agent.address}")
    ctx.logger.info(f"Claude binary: {CLAUDE_BIN or 'NOT FOUND on PATH'}")
    ctx.logger.info(f"Claude workdir: {CLAUDE_WORKDIR}")
    ctx.logger.info(f"Claude model: {CLAUDE_MODEL or '(default)'}")
    if CLAUDE_BIN is None:
        ctx.logger.warning("`claude` not found — requests will return an error.")


# --- Chat protocol (human chat via ASI:One / Agentverse) -------------------
chat_proto = Protocol(spec=chat_protocol_spec)


def _new_chat(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=content,
    )


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    # Acknowledge receipt (required by the chat protocol spec).
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    for item in msg.content:
        if isinstance(item, StartSessionContent):
            ctx.logger.info(f"Chat session started with {sender}")
            continue
        if isinstance(item, TextContent):
            ctx.logger.info(f"Request from {sender}: {item.text[:120]!r}")
            result = await run_claude_code(item.text, ctx.logger)
            await ctx.send(sender, _new_chat(result))
            ctx.logger.info(f"Replied to {sender}")


@chat_proto.on_message(ChatAcknowledgement)
async def handle_chat_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.debug(f"Ack from {sender} for {msg.acknowledged_msg_id}")


agent.include(chat_proto, publish_manifest=True)


# --- Direct agent-to-agent path --------------------------------------------
class ClaudeRequest(Model):
    prompt: str


class ClaudeResponse(Model):
    result: str


@agent.on_message(model=ClaudeRequest, replies=ClaudeResponse)
async def handle_request(ctx: Context, sender: str, msg: ClaudeRequest):
    ctx.logger.info(f"ClaudeRequest from {sender}: {msg.prompt[:120]!r}")
    result = await run_claude_code(msg.prompt, ctx.logger)
    await ctx.send(sender, ClaudeResponse(result=result))


if __name__ == "__main__":
    agent.run()
