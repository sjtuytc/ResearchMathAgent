# Research Math Agent — Web App

A Claude-powered agent that solves the *First Proof* benchmark problems in
`problems/`, with a live, step-by-step UI — modeled on
[TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany): a thin
agent loop over a model, plus a **Questions / Issues** workspace, pointed at
research mathematics instead of a simulated software company.

## Three views per question

The UI has a sidebar of questions (q1–q10) and three tabs:

- **Question** — the problem's `.tex` file, rendered (with KaTeX) and as raw source.
- **Issue** — a per-question markdown issue tracker (area, author, status, notes,
  and a log of agent runs). Editable and saved server-side. This is the
  question↔issue link you asked for, in the spirit of TheAgentCompany's task
  issues. Issues live in `webapp/issues/<id>.md` (auto-seeded from the problem,
  gitignored).
- **Agent** — run the solver live and watch every step (thinking, text with
  rendered math, tool calls + results, and the final `solution.tex` artifact).
  A "Log run to issue" button appends the result to the issue.

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

## Architecture

```
Browser (SSE) ──▶ FastAPI (server.py)
                    ├─ /api/problems · /api/problem/{id}      (Question view)
                    ├─ /api/issue/{id}  GET/POST · /activity   (Issue tracker)
                    └─ /api/solve?provider=claude-code|api     (live agent stream)
                          │
            provider=claude-code ──▶ claude_code.py: spawn `claude -p --output-format
                          │            stream-json`, translate events → UI (subscription)
            provider=api        ──▶ agent.py: Claude Messages API tool-use loop (API key)
                                       └─ tools.py: sandboxed read/write/python/latex
```

## Caveats

- These are research-level, open problems; treat agent output as a draft to
  inspect, not a verified solution.
- A subscription `claude -p` run can take a while and consumes your plan's usage.
