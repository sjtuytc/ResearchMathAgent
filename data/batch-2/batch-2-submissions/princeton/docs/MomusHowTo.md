# Momus pipeline — quickstart for a new collaborator

Active branch: `fix/bs-gate-ranking-and-double-extract` (also the
GitHub default branch — FP clones from here).

## Architecture in one paragraph

The pipeline runs **W** parallel solver agents per stage for up to
**D** stages on each problem. After each stage's W outputs, a
gauntlet of graders (3 draws + an aggregator) and a separate BS
detector vet each solver attempt; a notebook agent then synthesises
the surviving ideas into the next stage's notebook. When a solver
output passes the dual gate (gauntlet 7/7 AND BS-clean), a
cross-model OAI gate calls OpenAI gpt-5.5-pro as a second opinion —
the run only exits early if OpenAI also says ≥ 7. Otherwise the
gauntlet score is demoted to `min(gauntlet, openai)` and OpenAI's
critique flows into the next stage's notebook. When solver progress
stalls (median grader score flat for 2 consecutive stages), a
conjecture extractor proposes 1–2 load-bearing conjectures, and a
separate inner loop of **R** rounds attacks them (2/3 prove, 1/3
disprove). After the solver phase finishes per problem, **Grader 3**
runs a literature-grounded verification chain on the top-2 proofs
(librarian → fetch_and_distill → verify_pipeline → router) and
produces PASS / REWRITE / REWORK / UNVERIFIABLE; if the verdict
isn't PASS, the rework loop spawns a W=6 D=6 child run with Grader
3's evidence-grounded feedback as `additional_materials` and ships
whichever proof scores higher.

## The three graders

The pipeline runs three distinct grading systems, used in different
phases and at different cost / latency tradeoffs.

**1. Gauntlet grader (Gemini, fast, in-loop).** The same battle-tested
grader prompt (`src/math_solver/agents/grader.py`) is fired multiple
times per high-scoring candidate. Each call is one *draw*. For a
candidate that the initial grader rated ≥5, the gauntlet runs **2
draws + 1 aggregator** (= 3 calls); for a ≥7 candidate it runs **3
draws + 1 aggregator** (= 4 calls). The aggregator reads the draws'
critiques and writes a final consolidated verdict + score. Score is
final only when the aggregator agrees with the draws. The gauntlet
exists to absorb stochastic per-call noise. Each grader call is
~25K tokens and finishes in seconds.

**2. OpenAI cross-model grader (gpt-5.5-pro, slow, exit-only).** Same
prompt as the Gemini grader, different model. Fires only after the
Gemini gauntlet *confirms* a 7/7 — as a second opinion before exit.
The run exits early only if OpenAI also scores ≥ 7. Otherwise the
parent record's score is demoted to `min(gauntlet, openai)`, the
OpenAI critique is stored as `rec.openai_feedback`, and the pipeline
continues. Slow: each gpt-5.5-pro call takes ~3-5 minutes with
reasoning. Cost: ~$1-2 per call. Empirical motivation: 0 of 28
Gemini-gauntlet-confirmed-7s in a 2026-05-27 study also got
OpenAI ≥ 7 — the gauntlet has a systematic per-model blind spot
that a cross-model second opinion catches.

**3. Grader 3 (literature-grounded verifier, slowest, per problem).**
Not a single LLM call — a chain of four agents
(librarian → fetch_and_distill → verify_pipeline[^pdfvssummary] →
Flash router) that goes to actual published literature and checks
whether each cited step is supported by the cited source. Verdicts per step are
SUPPORTS / DOES NOT APPLY / CONTRADICTS / NOT FOUND, aggregated to
PASS / REWRITE / REWORK / UNVERIFIABLE per proof. Fires once per
problem on the top-2 proofs after the solver phase finishes (no
score threshold). Runtime: ~5-10 min per proof; ~$1-2 of SerpAPI +
Gemini Pro + Flash per proof. Output is evidence-grounded — its
`feedback.md` is what the rework loop hands to the next solver run
as `additional_materials`. The librarian's `gap_report.txt` is
seeded with BOTH the Gemini gauntlet critique and the OpenAI critique
("Grader A" / "Grader B" sections) so the parametric recall focuses
on the contested steps.

In short: gauntlet protects against single-call noise; OpenAI
protects against systematic Gemini bias; Grader 3 protects against
both by going outside the LLM substrate entirely and checking actual
papers.

**Implication for budget.** Any of the three graders can block
acceptance: the gauntlet by demoting the aggregator score below 7,
the OpenAI gate by scoring below 7 (which on 2026-05-27 empirics
happens on 28 of 28 gauntlet-7s), and Grader 3 by returning a
non-PASS verdict (which triggers a rework run). Because the three
gates are designed to be independent and *each* can fire, the
practical effect is that a run rarely exits early on the main loop's
OAI gate, almost always reaches the D=6 cap, and almost always
triggers the post-solver rework. Plan for `total_budget` and
wallclock as if **full D + rework will run** — that is the expected
case, not the worst case.

## The five parameters that matter

| Knob | Meaning | Today's default |
|---|---|---|
| **W** (`width`) | Parallel solver agents per stage. Each gets a different subset of the previous stage's outputs as `prev_attempts`. | **9** |
| **D** (`depth`) | Max stages per problem. Loop exits early on an OAI-confirmed 7/7. | **6** |
| **R** (`CONJECTURE_ROUNDS`) | Rounds of the conjecture-stage inner loop. Each round = W solvers attacking the active conjectures (2/3 prove + 1/3 disprove). One single-grader 7/7 closes a conjecture. | **2** |
| `total_budget` | Solver-cell budget across the lineage (parent + child spawns + successor spawns), NOT dollars. A single W=9 D=6 run uses 54 cells; budget 108 = 1 extra child generation. Auto-derived as `2WD` if not set. | **108** |
| `max_parallel` | Number of problems solved concurrently inside the container. 10 = all FP problems at once on r7i.2xlarge. Lower if RAM pressure surfaces. | **10** |

Cost rough-cut: a single W=9 D=6 problem run is ~$10–30 in Gemini
tokens; a full 10-problem FP submission is ~$100–300 including
Grader 3 SerpAPI + Flash distill costs.

## Launch defaults we used today

Per-deploy invocation (a thin wrapper around `terraform apply`):

```bash
./deploy/deploy.sh path/to/problems.json --region us-east-1
# defaults applied via deploy/terraform/variables.tf:
#   width = 9, depth = 6, max_parallel = 10
#   timeout_hours = 23, instance_type = r7i.2xlarge
#   gemini_model = (config default), search = false
```

`problems.json` is just `{"problems": [{"id": "Q2", "statement":
"..."}, ...]}`. Each problem's statement is the entire input the
solver sees as Input 1.

For parallel deploys (don't share a terraform state):

```bash
cp -r deploy/terraform /tmp/tf-myexp
rm -f /tmp/tf-myexp/terraform.tfstate*
terraform -chdir=/tmp/tf-myexp init
terraform -chdir=/tmp/tf-myexp apply -auto-approve \
  -var "region=us-east-1" \
  -var "ssm_key_param=/firstproof/gemini_api_key" \
  -var "problems_json_path=$PWD/problems.json" \
  -var "code_tarball_path=$TARBALL"
```

Outputs land in `s3://firstproof-<timestamp>/output/`:
`bootstrap.log`, `solutions.json`, `<id>.tex` per problem, and a
`runs/<rid>/run.db` per problem (inspect via `sqlite3 ... "SELECT *
FROM agent_calls"` for full LLM trace).

## Search is OFF; lit-search happens two other ways

`--search` (the Gemini-Pro grounded-search facility) is **not used**.
Solvers run with no web access. Literature enters the pipeline via
two distinct mechanisms:

**1. Grader 3 chain — post-solver, evidence-grounded verification.**
Fires after each problem's solver phase completes (and after the
top-K proofs are picked). Three packages chain together:

- **librarian** (`scripts/librarian.py`) — 3-stage parametric recall
  (gauntlet → narrower → chapter picker) over Gemini-Pro, producing
  candidate references (arXiv / DOI / ISBN). No web fetch.
- **fetch_and_distill** (`scripts/fetch_and_distill.py`) — SerpAPI
  to find PDF URLs, downloads them, verifies identity against
  expected metadata, distills first pages via Flash into compact
  `.md` summaries.
- **verify_pipeline** (`scripts/verify_pipeline.py`) — annotates
  each proof step against the librarian's findings, pinpoints the
  cited result in the source summary, then full-PDF verifies each
  pinpointed step → SUPPORTS / DOES NOT APPLY / CONTRADICTS / NOT
  FOUND. A Flash router aggregates to PASS / REWRITE / REWORK /
  UNVERIFIABLE.

The router's `feedback.md` (per-step non-SUPPORTS findings) is what
the rework loop hands to the next solver run as
`additional_materials` — evidence-grounded critique, not opinion.
Today's `gap_report.txt` to the librarian also embeds BOTH the
Gemini gauntlet aggregator's critique and the OAI grader's critique
as "Grader A" / "Grader B" sections, so the librarian focuses its
parametric recall on the contested steps.

**2. paper_hunter — mid-run, per-paper actionable extraction.**
Lives at `src/math_solver/agents/paper_hunter.py` and is wired into
`orchestrator.py` at three call sites (stages 4, mid-pipeline, and
end). Designed to read fetched papers in full and mine them for
genuinely new directions when the solver pipeline has exhausted its
current ideas. Currently dormant in main (`notebook.py:174`
hardcodes `search_queries=[]`) but **active prototyping is in
flight** on AWS as of 2026-05-28 PM: four parallel runs testing
search-query plumbing and seed-bundle integration. The plan is to
have paper_hunter as the main web-search entry point alongside
Grader 3's literature verification.

## Known gotchas surfaced 2026-05-28 evening

### Grader 3's chain degrades silently when an external dep is missing

Two distinct shipping fixes this evening, same shape of bug — a single
missing external dependency makes the literature-verification chain
return UNVERIFIABLE on every proof without firing a "FATAL: chain
unusable" alarm. Worth knowing because the verdict looks legitimate
("Grader 3 couldn't get enough PDFs to certify") but is actually a
deploy bug.

1. **`poppler-utils` missing in the image** (`ff9116e`). Without
   `pdftotext`, `fetch_and_distill`'s post-download verifier failed
   with `[Errno 2] No such file or directory: 'pdftotext'` on every
   PDF and reported `verified=false`. Every Grader 3 run on the
   2026-05-28 AM Q2+Q5 batch came back UNVERIFIABLE with 0 verified
   steps — not because the librarian failed but because the verifier
   couldn't read the PDFs it fetched.
2. **`pypdf` missing in the deploy venv** (`09aad42`). Once
   poppler-utils lands, the chain progresses to the `distill` step
   which uses `pypdf.PdfReader` to extract text into `summaries/<slug>.md`.
   `pypdf` was never pinned in `deploy/requirements.lock.txt`. Result:
   each PDF correctly *identifies* (the LLM pinpoint identity check
   succeeds) but never gets *summarized*, so `verify_pipeline` has
   zero summaries to feed its per-step pinpoint+classify chain.
   Verdict: UNVERIFIABLE again, structurally identical to the
   poppler case from a Grader 3 output perspective.

**Diagnostic when Grader 3 verdict is UNVERIFIABLE on every problem:**
SSH into the container (recipe below), check the run log for
`distill FAIL: <slug> — pypdf not installed in the active venv` or
`pdftotext_error: '[Errno 2] No such file or directory'`. Either
pattern means the chain is broken structurally, not the proofs
themselves.

### OpenAI demote currently no-ops (under investigation)

Discovered tonight by SSH'ing into the running Q9+Q10+QT container
and inspecting `run.db`: every parent record has `openai_score = None`
despite the log showing OpenAI gate calls firing multiple times
per run with `blocked exit (gauntlet=7, openai=3.0) — continuing
with effective score 3.0`. The demote code path
(`orchestrator.py:484-492`) writes `rec.score = eff_score` and
`rec.openai_feedback = openai_feedback_text` to a parent record
located via a `for rec in reversed(state.all_solutions): if
rec.stage == d and rec.solver_index == si and rec.stage_type ==
"parent"` walk — but the lookup apparently finds nothing, so both
writes silently no-op.

Leading hypothesis: parent records are added to
`state.all_solutions` *after* the OAI gate runs in the same stage,
so the lookup at OAI-gate time finds nothing to demote against.

**Consequence:** every "score=7.0" reported in tonight's
`solutions.json` is the gauntlet-7, **not OAI-confirmed**. The
shipped `<id>.tex` files reflect the gauntlet+BS gates, but the
cross-model second opinion was dropped on the floor. The
architecture description in §"OpenAI cross-model grader" above
describes the intended behaviour; the demote does not actually
apply in production until this is fixed.

To check on a finished run.db whether the demote fired:

```python
import sqlite3, json
db = sqlite3.connect("runs/<rid>/run.db")
state = json.loads(db.execute("SELECT value FROM state WHERE key='run_state'").fetchone()[0])
parents = [x for x in state["all_solutions"] if x.get("stage_type")=="parent"]
n7_with_oai = sum(1 for p in parents if p.get("score")==7.0 and p.get("openai_score") is not None)
n7_without_oai = sum(1 for p in parents if p.get("score")==7.0 and p.get("openai_score") is None)
print(f"7.0 parents with OAI demote applied: {n7_with_oai}")
print(f"7.0 parents missed by demote:        {n7_without_oai}")
```

Healthy run: all `score=7.0` parents should have a non-None
`openai_score` (either ≥7 → confirmed, or <7 → would have demoted
to that openai value, except `rec.score` is also updated, so
`score=7.0` with `openai_score < 7` should not coexist).

### Per-problem `--additional-materials` is now plumbed (`17b6db8`)

`batch._launch_run` now accepts an optional `additional_materials_path`
and `run_firstproof.handle` looks up `<input_dir>/seeds/<problem_id>_seed.{md,txt}`
to thread to the spawned solver run. Convention for adding a seed
bundle alongside a problems.json:

```
input_dir/
├── problems.json     # FP-style
└── seeds/
    └── Q2_seed.md    # any seed bundle for problem id "Q2"
```

Convention is filename-keyed by problem id — no schema change to
`problems.json`. Empty `seeds/` → baseline behaviour preserved.
Use cases: hand-built paper_hunter bundles, prior-run best-of
seeds, externally-curated reference packs.

### `GEMINI_CONCURRENCY` env var now actually takes effect (`06e1216`)

Before this commit, the in-flight semaphore in `gemini.py` was
hardcoded at `asyncio.Semaphore(6)` despite the terraform variable
`gemini_concurrency` and the container env `-e GEMINI_CONCURRENCY=…`
both being plumbed for years. Both were dead values. Now driven by
`int(os.environ.get("GEMINI_CONCURRENCY", "6"))`. Recommendation:
bump to **9** to match W=9 (otherwise the W parallel solver calls
queue into two sub-batches per stage and the wallclock takes a
~1.5× hit). For tomorrow's 10-problem FP submission, **16** is a
safe upper bound.

## Diagnostic — SSH into a running container

`bootstrap.log` and per-run logs only upload to S3 at container
exit. To inspect a running container live, you need SSH access. The
deploy doesn't open port 22 by default (security group is closed);
the recipe below opens it temporarily, pushes a 60-second-TTL key via
EC2 Instance Connect, and tails the relevant log.

```bash
# 1. Authorize your IP for SSH on the instance's security group.
INSTANCE=i-XXXXXXXX
SG=$(aws ec2 describe-instances --instance-ids $INSTANCE \
       --query 'Reservations[].Instances[].SecurityGroups[0].GroupId' \
       --output text --region us-east-1)
MYIP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id $SG --region us-east-1 \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MYIP/32}]"

# 2. Push a temporary SSH key via EC2 Instance Connect (key valid 60s).
ssh-keygen -t ed25519 -N "" -f ~/.ssh/fp_tmp -q
aws ec2-instance-connect send-ssh-public-key --region us-east-1 \
  --instance-id $INSTANCE --instance-os-user ubuntu \
  --ssh-public-key file://$HOME/.ssh/fp_tmp.pub

# 3. SSH and tail.
PUB=$(aws ec2 describe-instances --instance-ids $INSTANCE --region us-east-1 \
       --query 'Reservations[].Instances[].PublicIpAddress' --output text)
ssh -i ~/.ssh/fp_tmp -o StrictHostKeyChecking=no ubuntu@$PUB \
  'sudo tail -100 /var/log/firstproof-bootstrap.log'
# Per-problem solver logs (inside docker volume):
ssh -i ~/.ssh/fp_tmp -o StrictHostKeyChecking=no ubuntu@$PUB \
  'sudo ls /opt/firstproof/data/runs/firstproof_*/*.log'
```

The pushed key expires after 60 seconds. For longer sessions, re-push
between commands. To copy a `run.db` off the box mid-run:

```bash
ssh -i ~/.ssh/fp_tmp ubuntu@$PUB 'sudo cp /opt/firstproof/data/runs/<rid>/run.db /tmp/r.db && sudo chmod 644 /tmp/r.db'
scp -i ~/.ssh/fp_tmp ubuntu@$PUB:/tmp/r.db ./local_r.db
```

Remember to revoke the SSH ingress rule when done:

```bash
aws ec2 revoke-security-group-ingress --group-id $SG --region us-east-1 \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MYIP/32}]"
```

## Footnotes

[^pdfvssummary]: `verify_pipeline` uses a hybrid of distilled
    summaries and full PDFs. Stage 3a (the *pinpointer* — "where in
    this paper does the cited claim live?") reads the
    Flash-distilled `summaries/<slug>.md` (typically 5–15K
    chars) — a cheap routing step. Stage 3b (the *literature
    findings* call — the actual "does the cited theorem support the
    proof step, with all hypotheses?" verification) reads the **full
    PDF text** via `pdftotext_full(pdfs/<slug>.pdf)`, typically
    50–200K chars per paper. PDFs are cached per run so each is
    parsed off disk only once. Trade-off if you ever want to drop
    summaries: stage 3a would become a heavier Pro call but might
    catch cases where the summary distillation dropped a relevant
    subsection.
