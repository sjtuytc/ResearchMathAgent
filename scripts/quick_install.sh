#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RMA quickstart installer.
#
# Goal: after this script you can run
#
#       rma solve q6
#
# and it solves a research-level math problem on YOUR OWN Claude Pro/Max
# subscription (via the local `claude` CLI). It never uses Google Vertex AI and
# never a developer's API key — every run is billed to your subscription.
#
# Usage:
#       git clone https://github.com/sjtuytc/ResearchMathAgent
#       cd ResearchMathAgent
#       ./scripts/quick_install.sh    # re-running later pulls the latest code first
#       source .venv/bin/activate     # (only if the installer created a venv)
#       claude login                  # log in with your subscription
#       rma solve q6
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

bold(){ printf '\033[1m%s\033[0m\n' "$*"; }
ok(){   printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$*"; }
err(){  printf '  \033[31m✗\033[0m %s\n' "$*"; }

bold "==> RMA quickstart install"

# 0) Pull the latest code from the remote ─────────────────────────────────────
# So a re-run always installs the newest version, not a stale local checkout.
# Conservative: fast-forward only, and skip cleanly (no clobber, no auto-merge)
# when there is no remote, a detached HEAD, or uncommitted local changes.
bold "==> Updating to the latest code from the remote"
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  REMOTE="$(git remote | head -n1 || true)"
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  if [ -z "$REMOTE" ]; then
    warn "no git remote configured — skipping pull"
  elif [ "$BRANCH" = "HEAD" ]; then
    warn "detached HEAD — skipping pull"
  elif ! git diff --quiet || ! git diff --cached --quiet; then
    warn "uncommitted local changes — skipping pull (commit or stash, then re-run to update)"
  elif git pull --ff-only "$REMOTE" "$BRANCH" >/tmp/rma_git.log 2>&1; then
    ok "updated from $REMOTE/$BRANCH  ($(git rev-parse --short HEAD))"
  else
    warn "could not fast-forward from $REMOTE/$BRANCH — continuing with current checkout (see /tmp/rma_git.log)"
  fi
else
  warn "not a git checkout — skipping pull (install proceeds with current files)"
fi

# 1) Python 3.10+ ─────────────────────────────────────────────────────────────
# Prefer a versioned interpreter — the default `python3` is often too old.
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
  c="$(command -v "$cand" 2>/dev/null || true)"
  [ -z "$c" ] && continue
  if "$c" -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  err "Python >= 3.10 is required but none was found (tried python3.13 … python3)."
  err "Install Python 3.10+ and re-run."
  exit 1
fi
ok "Python $("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')  ($PY)"

# 2) Install the rma CLI into a virtualenv ────────────────────────────────────
# A venv is the portable choice: its site-packages is always importable, unlike
# `--user` installs (which break when PYTHONNOUSERSITE=1) or read-only system
# Pythons. We install via the venv's OWN python so packages land inside it.
ACTIVATE=""
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
  bold "==> Using your active virtualenv ($VIRTUAL_ENV)"
  VENV_PY="${VIRTUAL_ENV}/bin/python"
  RMA_BIN="${VIRTUAL_ENV}/bin/rma"
else
  bold "==> Creating a virtualenv at ./.venv"
  "$PY" -m venv .venv
  VENV_PY="$ROOT/.venv/bin/python"
  RMA_BIN="$ROOT/.venv/bin/rma"
  ACTIVATE="source .venv/bin/activate"
  ok "created ./.venv"
fi

"$VENV_PY" -m pip install --upgrade pip >/tmp/rma_pip.log 2>&1 || true
if "$VENV_PY" -m pip install -e . >>/tmp/rma_pip.log 2>&1; then
  ok "installed the rma CLI"
else
  err "pip install failed — see /tmp/rma_pip.log"; tail -8 /tmp/rma_pip.log; exit 1
fi

# 3) Claude Code CLI — the backend that bills YOUR subscription ────────────────
bold "==> Checking the Claude Code CLI (your subscription backend)"
if command -v claude >/dev/null 2>&1; then
  ok "claude CLI  ->  $(command -v claude)"
else
  warn "claude CLI not found."
  if command -v npm >/dev/null 2>&1; then
    echo "    Installing it:  npm install -g @anthropic-ai/claude-code"
    if npm install -g @anthropic-ai/claude-code >/tmp/rma_npm.log 2>&1; then
      ok "installed Claude Code"
    else
      warn "auto-install failed — run it yourself:  npm install -g @anthropic-ai/claude-code  (see /tmp/rma_npm.log)"
    fi
  else
    warn "Node/npm not found. Install Node 18+, then:  npm install -g @anthropic-ai/claude-code"
  fi
fi

# 4) Verify the CLI actually runs ─────────────────────────────────────────────
bold "==> Verifying the rma CLI"
if "$RMA_BIN" --help >/dev/null 2>&1; then
  ok "rma works  ($RMA_BIN)"
else
  err "rma did not run — see /tmp/rma_pip.log"; exit 1
fi

# Done ────────────────────────────────────────────────────────────────────────
printf '\n'
bold "Done — solve a problem on YOUR Claude subscription:"
cat <<EOF

EOF
[ -n "$ACTIVATE" ] && printf '  0) Activate the environment (each new shell):\n       %s\n\n' "$ACTIVATE"
cat <<'EOF'
  1) Log in with YOUR Claude subscription (Pro/Max):
       claude login

  2) Solve a problem on your subscription:
       rma solve q6

  Billing: `rma solve` uses the Claude Code backend = your `claude login`
  subscription. It never touches Google Vertex AI or a developer API key.

  Offline dry-run (no LLM, just the skeleton):
       rma solve q6 --model-name rma-skeleton
EOF
