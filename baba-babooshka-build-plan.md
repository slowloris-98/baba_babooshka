# Baba Babooshka — build plan

**Context:** AI Hackathon @ UC Berkeley, June 20–21, 2026. Time budget: ~1.5 days. This plan is scoped to ship a working demo, not a finished product. Follow the phases in order — do not start Phase 2 work before Phase 1's acceptance criteria pass.

**Architecture is locked.** Four components only. Do not introduce a different orchestration framework, a different memory store, a different error tracker, or a different chat surface. If something in this plan seems to require a fifth component, stop and flag it instead of adding one.

---

## 1. Components and responsibilities

| Component | Role | Exposed via | Docs |
|---|---|---|---|
| **uAgent** (Fetch.ai `uagents` framework) | Main orchestrator. Starts and runs work sessions: Claude Code sessions, planning sessions, project-scaffolding sessions. | Must expose an MCP server interface so Poke can trigger it. | [Getting started](https://uagents.fetch.ai/docs/getting-started/create) |
| **Redis Agent Memory Server** (`redis/agent-memory-server`) | Memory layer. Stores working memory (per-session) and long-term memory (persistent, searchable) for every task/project the agent works on. | Ships its own MCP server (`agent-memory mcp`) — use as-is, do not reimplement. | [GitHub repo](https://github.com/redis/agent-memory-server) |
| **Sentry** | Error tracking for the uAgent's processes. | Sentry's hosted MCP server — use as-is, do not reimplement. | [Education plan](https://sentry.io/for/education) · [Quickstarts](https://docs.sentry.io) |
| **Poke** | Human-facing communication layer (text/iMessage). Connects to the above three as MCP integrations and lets the user ask about project progress (via the memory server MCP) and errors (via the Sentry MCP). | N/A — Poke is the MCP *client*, not something we build. | [Managing integrations](https://poke.com/docs/managing-integrations) · [Custom MCP servers](https://interaction.co/mcp) |

**Data flow (do not deviate from this shape):**

```
User (iMessage/SMS)
   ↕
Poke  ──MCP──>  Redis memory server   (read: project/task status)
   ├──MCP──>  Sentry                (read: error data)
   └──MCP──>  uAgent                (trigger: start a session)

uAgent
   ├──spawns──>  Code session / Planning session / Project session
   ├──writes──>  Redis memory server  (session state, progress, results)
   └──reports──>  Sentry              (errors raised during a session)
```

Poke never talks to the uAgent's internals directly — only through whatever MCP tools the uAgent exposes. The uAgent never talks to the user directly — only through what it writes to Redis memory / Sentry, which Poke then surfaces.

---

## 2. Repo structure

```
baba-babooshka/
├── docker-compose.yml          # redis + agent-memory api + agent-memory mcp
├── .env.example
├── uagent/
│   ├── orchestrator.py         # uAgent definition, message handlers
│   ├── mcp_server.py           # exposes uAgent as an MCP server for Poke
│   ├── sessions/
│   │   ├── code_session.py     # Phase 2 — build first
│   │   ├── planning_session.py # Phase 3 — stretch
│   │   └── project_session.py  # Phase 3 — stretch
│   ├── memory_client.py        # wraps agent-memory-client SDK calls
│   └── sentry_init.py          # 5-line Sentry SDK init, imported first
├── memory/
│   └── schema.md               # memory key conventions, see §4
└── README.md                   # setup + demo script
```

---

## 3. Build phases

### Phase 1 — infra wiring (target: first 3–4 hours)

Tasks:
1. `docker-compose up api redis` for the Redis Agent Memory Server in **development mode** (asyncio task backend, no separate worker needed for a demo).
2. Run `agent-memory mcp --mode sse --port 9000` and confirm it responds.
3. Claim the Sentry education plan (`.edu` email at `sentry.io/for/education`, auto-activates via GitHub Student Developer Pack). Add the SDK init (~5 lines) to `uagent/sentry_init.py`, imported first thing in `orchestrator.py`.
4. Scaffold the uAgent itself using the `uagents` Python framework. Don't build session logic yet — just get an agent process running and confirm Sentry catches a deliberately-raised test exception.
5. In Poke (`poke.com/integrations/new`), connect:
   - Redis memory MCP server (URL from step 2)
   - Sentry MCP server (hosted, per Sentry's docs)

**Acceptance criteria for Phase 1:** Poke can answer "do you see any errors?" (empty, but the MCP call succeeds) and "what's in memory?" (empty, but the MCP call succeeds). The uAgent process runs and a forced exception shows up in the Sentry dashboard.

### Phase 2 — the thin vertical slice (target: next 6–8 hours)

Build **one session type only: Code session.** Do not start Planning or Project sessions yet.

Tasks:
1. `uagent/mcp_server.py`: expose exactly one MCP tool, e.g. `start_code_session(prompt: str, project_id: str)`. This is what Poke calls when the user asks to start work.
2. `uagent/sessions/code_session.py`: spawns a Claude Code session against the given prompt. Keep this as simple as possible — a subprocess call is fine for a hackathon.
3. On session start, write a working-memory entry (`session started`). On completion (success or failure), write a long-term memory entry with the outcome — see schema in §4.
4. On any exception during the session, let Sentry catch it (it already will, from Phase 1's init) — don't add a second error path.
5. Connect the uAgent's MCP server to Poke as the third integration.

**Acceptance criteria for Phase 2:** From Poke, the user can say "start a code session for [X]" and it actually runs. After it finishes, "what's the status of my project?" returns a real answer pulled from Redis memory, not a placeholder.

### Phase 3 — demo polish (target: remaining time)

Pick from this list in priority order — stop whenever you're out of time, each item is independently optional:

1. **Seer relay (high value, low cost):** when the user asks "what broke?", have the Sentry MCP response include Seer's AI-suggested root cause, not just the raw stack trace. Sentry's free education plan includes Seer AI credits — use them.
2. **Planning session:** second session type, scopes a request into steps before any code is written. Same write-to-memory pattern as Code session.
3. **Project session:** third session type, scaffolds a new repo. Same write-to-memory pattern.
4. **Proactive push:** instead of only answering when asked, have the uAgent POST to Poke's inbound webhook (`https://poke.com/api/v1/inbound-sms/webhook`) when a session finishes, so the user gets a text without asking.

**Do not start Phase 3 if Phase 2's acceptance criteria haven't passed.** A working one-session-type demo beats three half-built session types.

---

## 4. Memory schema (Redis Agent Memory Server)

Use the SDK's existing `user_id` / `session_id` / `memory_type` fields rather than inventing a parallel scheme.

- `user_id`: the hackathon user (single-user for this demo — don't build multi-user auth).
- `session_id`: one per session run (one per Code/Planning/Project invocation).
- Working memory: live progress within a session (e.g. "session started", "step 2 of 4").
- Long-term memory: the durable record once a session ends — what was asked, what was done, outcome (success/failure), and a pointer to the relevant Sentry issue if it failed. This is what "what's my project status" queries resolve against.

Don't build a separate "projects" table elsewhere — `project_id` should just be metadata on memory entries, filtered via the memory server's existing search.

---

## 5. Explicit non-goals for this hackathon build

- Multi-user authentication.
- A custom UI — Poke (text/iMessage) is the only interface.
- Reimplementing Redis or Sentry's MCP servers — use what they ship.
- Background task workers (Docket) for the memory server — asyncio backend is enough for a demo.
- More than one session type before Phase 2's acceptance criteria pass.

---

## 6. Demo script (what you should be able to show)

1. Text Poke: "start a code session to build a CLI todo app."
2. uAgent runs the session, writes progress to Redis memory.
3. Text Poke: "how's it going?" → answer pulled live from Redis memory MCP.
4. (If something breaks) Text Poke: "did anything error?" → answer pulled from Sentry MCP, ideally with Seer's suggested fix.
5. Text Poke: "what's the status now?" → final outcome from long-term memory.

---

## 7. Reference links

- **uAgents (Fetch.ai)** — getting started: https://uagents.fetch.ai/docs/getting-started/create
- **Redis Agent Memory Server** — repo, quick start, MCP config: https://github.com/redis/agent-memory-server
- **Sentry** — claim the free education plan: https://sentry.io/for/education
- **Sentry** — per-language SDK quickstarts: https://docs.sentry.io
- **Poke** — managing integrations / connecting MCP servers: https://poke.com/docs/managing-integrations
- **Poke** — custom MCP server template + webhook API: https://interaction.co/mcp
