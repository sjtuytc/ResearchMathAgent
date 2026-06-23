"""Initialize everything for first_proof_2 (prob-01..prob-10): concepts,
per-question insights, dataset insight, and the per-question documents.

Meetings already exist (substantive). Runs via the Vertex global endpoint.
"""
import glob
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
REPO = Path("/projects/bhov/zzhao18/code/ResearchMathAgent-web")
sys.path.insert(0, str(REPO))
PIDS = [f"prob-{i:02d}" for i in range(1, 11)]
print("=== FP2 INIT START ===", flush=True)

# 1) Concepts for every fp2 problem missing them (Vertex).
try:
    from webapp.concepts import ensure_fp2_concepts
    ensure_fp2_concepts(REPO)
    print("[concepts] ensure_fp2_concepts complete", flush=True)
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"[concepts] FAILED: {e}", flush=True)

# 2) Per-question insights (Vertex).
from webapp.insight_agents import generate_question_insight, generate_dataset_insight
for pid in PIDS:
    try:
        d = generate_question_insight(REPO, pid, "first_proof_2")
        print(f"[insight] {pid} ok :: {str(d.get('summary') or d.get('title') or '')[:60]!r}", flush=True)
    except Exception as e:
        print(f"[insight] {pid} FAILED: {e}", flush=True)

# 3) Dataset-level insight for first_proof_2 (Vertex).
try:
    generate_dataset_insight(REPO, "first_proof_2")
    print("[insight] dataset first_proof_2 ok", flush=True)
except Exception as e:
    print(f"[insight] dataset FAILED: {e}", flush=True)

# 4) Per-question documents (overview/timeline/progress/strategies).
from webapp.rich_documents import update_question_document
for pid in PIDS:
    try:
        update_question_document(REPO, pid)
        print(f"[docs] {pid} ok", flush=True)
    except Exception as e:
        print(f"[docs] {pid} FAILED: {e}", flush=True)

# Summary for review.
print("=== FP2 INIT SUMMARY ===", flush=True)
for pid in PIDS:
    qdir = REPO / "documents" / "questions" / pid
    concepts = (qdir / "concepts.json")
    ncon = 0
    if concepts.is_file():
        try:
            ncon = len(json.loads(concepts.read_text()))
        except Exception:
            ncon = -1
    insight = list(glob.glob(str(REPO / f"webapp/insights/questions/**/{pid}.json"), recursive=True))
    docs = len(glob.glob(str(qdir / "*.tex")))
    print(f"  {pid}: concepts={ncon} insight={'yes' if insight else 'no'} doc_tex={docs}", flush=True)
print("=== FP2 INIT DONE ===", flush=True)
