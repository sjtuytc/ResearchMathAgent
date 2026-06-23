"""Standalone push-forward runner — decoupled from the uvicorn --reload dev
server so it is not killed when watchfiles reloads the worker.

Resolves up to max_resolve open issues per problem, runs a 1-round meeting +
synthesis, and persists a real run record to push_forward_state.json at the end.
"""
import logging
import sys
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)

REPO = Path("/projects/bhov/zzhao18/code/ResearchMathAgent-web")
sys.path.insert(0, str(REPO))

from webapp.push_forward import run_push_forward  # noqa: E402

job_id = uuid.uuid4().hex
print(f"STANDALONE PUSH-FORWARD START job_id={job_id}", flush=True)
try:
    run_push_forward(
        REPO,
        job_id,
        problems=["q1", "q2", "q4", "q5", "q7"],
        max_resolve=25,
        n_meeting_rounds=1,
        dataset="first_proof_1",
    )
    print(f"STANDALONE PUSH-FORWARD DONE job_id={job_id}", flush=True)
except Exception as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print(f"STANDALONE PUSH-FORWARD FAILED job_id={job_id}: {exc}", flush=True)
