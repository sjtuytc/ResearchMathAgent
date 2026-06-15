# Research Math Agent — Web App

A Claude-powered agent that solves the *First Proof* benchmark problems in
`problems/`, with a live, step-by-step UI — modeled on
[TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany): a thin
agent loop over a model, plus a **Questions / Issues** workspace, pointed at
research mathematics instead of a simulated software company.

## Four tabs

The UI has a sidebar of questions (q1–q10) and four tabs:

- **Question** — the problem's `.tex` file, rendered (with KaTeX) and as raw source.
- **Issue** — a per-question markdown issue tracker (area, author, status, notes,
  and a log of agent runs). Editable and saved server-side. This is the
  question↔issue link, in the spirit of TheAgentCompany's task issues. Issues
  live in `webapp/issues/<id>.md` (auto-seeded from the problem, gitignored).
- **Agent** — run the solver live and watch every step (thinking, text with
  rendered math, tool calls + results, and the final `solution.tex` artifact).
  A "Log run to issue" button appends the result to the issue.
- **Documents** — browse the daily reports written by the autonomous worker (and
  on-demand runs), with a "Generate today's report" button. Reports live in the
  repo-level `documents/` directory.

## Two ways to call Claude

Pick the provider in the Agent tab:

### 1. Claude Code — your Pro/Max **subscription** (default, no API credits)

This drives the local `claude` CLI in headless mode, so runs draw from your
**monthly subscription** instead of per-token API billing. This is the answer to
"the API is too expensive": it packages the task and streams it through the
`claude` shell command you already pay for.

Requirements:

```bash
npm install -g @anthropic-ai/claude-code   # if not already installed
claude login                                # log in with your Pro/Max plan
```

Notes:
- Auth uses your `claude login` OAuth credentials. The server **unsets**
  `ANTHROPIC_API_KEY` for the CLI subprocess, because an API key would override
  subscription billing.
- Each run executes in an **isolated scratch directory outside the repo**, seeded
  with only `problem.tex` + `preamble.tex`, so the agent cannot read the blocked
  benchmark solution directories.
- Models: `sonnet` (default), `opus`, `haiku`, or a full id.
- Permissions: runs with `--permission-mode acceptEdits` + an explicit tool
  allowlist (`Read Write Edit Bash Glob Grep`) so it works autonomously and even
  under root.

### 2. Anthropic API — `ANTHROPIC_API_KEY` (billed per token)

The native Messages API tool-use loop (`webapp/agent.py`): streaming, adaptive
thinking, prompt caching, and a sandboxed math tool surface (`webapp/tools.py`)
that enforces the same `blocked_input_dirs` rule.

## Run it

```bash
pip install -e ".[webapp]"     # installs fastapi + uvicorn (+ anthropic for API mode)
python -m webapp               # serves http://127.0.0.1:8000 (override with HOST/PORT)
```

Open <http://127.0.0.1:8000>, pick a question, open the **Agent** tab, choose
**Claude Code (subscription)**, and hit **Solve**.

### On a Linux server with port forwarding

Default bind is `127.0.0.1:8000`, which is exactly right for SSH local
forwarding from your laptop:

```bash
# on the server
python -m webapp                      # binds 127.0.0.1:8000

# on your laptop
ssh -L 8000:localhost:8000 user@server
# then open http://localhost:8000
```

If you forward by binding the server's interface instead, set
`HOST=0.0.0.0 PORT=8000 python -m webapp` (and restrict access at the firewall —
the app has no auth). The `claude` CLI and your `claude login` session must live
on the **server**, since that's where the agent process runs.

## Run control (full frontend↔backend lifecycle)

Each run gets a `run_id`. The **Stop** button doesn't just close the browser
stream — it calls `POST /api/cancel`, which sets a cancel flag and **kills the
backend process group** (the `claude` CLI plus its node child), so a stopped run
stops consuming your subscription immediately. Cancellation also fires on tab
close (via `keepalive` fetch). For the API provider, the loop is cancelled
between turns and mid-stream.

Control endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/runs` | List active runs (id, problem, provider, age) |
| `POST /api/cancel` `{run_id}` | Stop a specific run; kills its process group |

## Autonomous daily worker

Runs the agent on its own, once a day, with no human in the loop — using the
`claude` CLI (your subscription, no API credits). Each day it works one or more
benchmark problems, writes a dated report into `documents/`, and logs the run to
each problem's issue. Open a shell on the server and run:

```bash
python -m webapp.daily            # daemon: run every day at $RMA_DAILY_AT (default 09:00)
python -m webapp.daily --now      # run once now, then keep the daily schedule
python -m webapp.daily --once     # run once and exit (use from cron)
```

Keep it alive across logout with `nohup`/`tmux`/systemd, e.g.:

```bash
nohup python -m webapp.daily --now > documents/daily.log 2>&1 &
```

Configuration (env vars):

| Var | Default | Meaning |
|---|---|---|
| `RMA_DAILY_AT` | `09:00` | Daily run time (server local, `HH:MM`) |
| `RMA_DAILY_PROBLEMS` | one rotating problem/day | Comma list, e.g. `q6` or `q1,q2` |
| `RMA_DAILY_MODEL` | `sonnet` | `claude` model alias |

`Ctrl-C`/`SIGTERM` cancels the in-flight run (kills the `claude` process group)
and exits cleanly. You can also trigger one run from the **Documents** tab
("Generate today's report"), which calls `POST /api/run-daily`.

Documents endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/documents` | List reports (name, title, modified, size) |
| `GET /api/document/{name}` | Read one report's markdown |
| `POST /api/run-daily` | Trigger one daily run in the background |

## Architecture

```
Browser (SSE) ──▶ FastAPI (server.py)
                    ├─ /api/problems · /api/problem/{id}        (Question view)
                    ├─ /api/issue/{id}  GET/POST · /activity     (Issue tracker)
                    ├─ /api/documents · /api/document/{name}     (Documents tab)
                    ├─ /api/runs · /api/cancel · /api/run-daily  (run control)
                    └─ /api/solve?provider=claude-code|api       (live agent stream)
                          │
            provider=claude-code ──▶ claude_code.py: spawn `claude -p --output-format
                          │            stream-json`, translate events → UI (subscription)
            provider=api        ──▶ agent.py: Claude Messages API tool-use loop (API key)
                                       └─ tools.py: sandboxed read/write/python/latex

runs.py     — cancellable run registry (process-group kill)
daily.py    — autonomous daily worker → documents/<date>.md  (cron/daemon)
documents.py, issues.py — markdown stores for reports and per-question issues
```

### Files

| File | Role |
|---|---|
| `server.py` | FastAPI app: SPA + all `/api/*` endpoints |
| `agent.py` | API-provider agent loop (Messages API, tool use, cancellable) |
| `claude_code.py` | Subscription provider: drives the `claude` CLI, streams events |
| `tools.py` | Sandboxed math tools + the `blocked_input_dirs` enforcement |
| `runs.py` | Run registry + cancellation / process-group kill |
| `daily.py` | Autonomous daily worker (daemon / cron / on-demand) |
| `documents.py` | Daily-report store (read/list/append) |
| `issues.py` | Per-question issue trackers |
| `static/index.html` | Single-page UI (4 tabs, live stream, KaTeX) |

## Caveats

- These are research-level, open problems; treat agent output as a draft to
  inspect, not a verified solution.
- A subscription `claude -p` run can take a while and consumes your plan's usage.
