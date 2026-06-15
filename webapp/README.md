# Research Math Agent — Web App

A Claude-powered agent that solves the *First Proof* benchmark problems in
`problems/`, with a live, step-by-step UI. Architecturally it mirrors
[TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany): a thin
agent loop on top of a model API, pointed at a task domain — here, research
mathematics instead of a simulated software company.

```
Browser (SSE)  ──▶  FastAPI (webapp/server.py)
                       │  run_agent() generator
                       ▼
              Agent loop (webapp/agent.py)
                 observe → Claude (stream + tool use) → run tool → feed back → repeat
                       │
                       ▼
              Sandboxed tools (webapp/tools.py)
                 read_problem · read_file · write_file · run_python · latex_check
```

## What it does

- Pick a problem (q1–q10) and a model, hit **Solve**.
- Watch Claude think, call tools, and write a proof to a scratch workspace —
  streamed live (thinking blocks, assistant text with rendered LaTeX, and every
  tool call + result).
- The agent loop is the standard Claude tool-use loop (manual loop for
  fine-grained event streaming), with adaptive thinking and prompt caching on
  the stable prefix.

## The tool surface (math-adapted)

| Tool | Purpose |
|---|---|
| `list_problems` | Enumerate benchmark problems |
| `read_problem` | Read a problem's LaTeX statement |
| `read_file` | Read `problems/` or `skills/` or the agent's workspace |
| `write_file` | Write a draft proof / script into the workspace |
| `run_python` | Numerically sanity-check claims (60s, no network) |
| `latex_check` | Compile a `.tex` with latexmk/pdflatex (no-op if absent) |

### Sandbox / benchmark integrity

Every file access is sandboxed. The agent can read only `problems/`, `skills/`,
and its own per-session scratch workspace (`webapp/.runs/<id>/`, gitignored). It
can **never** read the benchmark solution directories — `output_solutions`,
`final_solutions`, `baselines`, `skill_solutions` — matching
`config/default.yaml`'s `blocked_input_dirs` and the STRICT RULE in `CLAUDE.md`.
This is enforced in `webapp/tools.py`, not by trust.

## Run it

```bash
# 1. install the web app extra
pip install -e ".[webapp]"

# 2. provide your key (the Anthropic SDK reads this automatically)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. start the server (defaults to 127.0.0.1:8000; override with HOST/PORT)
python -m webapp
```

Then open <http://127.0.0.1:8000>.

The default model is `claude-opus-4-8`. You can type any model id in the UI
(e.g. `claude-sonnet-4-6` or `claude-haiku-4-5` for cheaper/faster runs).

## Notes

- These problems are research-level and open-ended; treat the agent's output as
  a draft attempt to inspect, not a verified solution.
- Each run gets a fresh workspace under `webapp/.runs/`. The agent's
  `solution.tex` and any scripts live there after a run.
