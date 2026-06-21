"""Local end-to-end test of agent.py's real handlers via a uAgents Bureau.

Runs the actual worker `agent` from agent.py plus a throwaway client in one
process. The client sends a ClaudeRequest; the worker spawns Claude Code and
replies with a ClaudeResponse. Exits 0 on success, 1 on timeout/failure.
"""

import asyncio
import importlib.util
import os
import sys

# Keep the spawned Claude run short for the test.
os.environ.setdefault("CLAUDE_MAX_TURNS", "3")
os.environ.setdefault("AGENT_SEED", "test-worker-seed")
os.environ.setdefault(
    "CLAUDE_WORKDIR", os.path.join(os.path.dirname(__file__), "workspace")
)
os.makedirs(os.environ["CLAUDE_WORKDIR"], exist_ok=True)

from uagents import Agent, Bureau, Context  # noqa: E402

# Import the real agent module (registers the worker's handlers).
spec = importlib.util.spec_from_file_location("agent", "agent.py")
agent_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_mod)

worker = agent_mod.agent
ClaudeRequest = agent_mod.ClaudeRequest
ClaudeResponse = agent_mod.ClaudeResponse

client = Agent(name="test_client", seed="test-client-seed")

PROMPT = "Reply with exactly the word PONG and nothing else."
got_reply = {"ok": False}


@client.on_event("startup")
async def send_request(ctx: Context):
    ctx.logger.info(f"Sending ClaudeRequest to worker {worker.address}")
    await ctx.send(worker.address, ClaudeRequest(prompt=PROMPT))


@client.on_message(model=ClaudeResponse)
async def on_response(ctx: Context, sender: str, msg: ClaudeResponse):
    ctx.logger.info(f"Got ClaudeResponse: {msg.result!r}")
    got_reply["ok"] = True
    print(f"\nTEST RESULT: worker replied -> {msg.result!r}")
    print("TEST PASSED" if "PONG" in msg.result else "TEST FAILED (unexpected text)")
    os._exit(0 if "PONG" in msg.result else 1)


async def watchdog():
    await asyncio.sleep(90)
    if not got_reply["ok"]:
        print("\nTEST FAILED: timed out waiting for ClaudeResponse")
        os._exit(1)


bureau = Bureau(port=8100, endpoint=["http://127.0.0.1:8100/submit"])
bureau.add(worker)
bureau.add(client)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(watchdog())
    bureau.run()
