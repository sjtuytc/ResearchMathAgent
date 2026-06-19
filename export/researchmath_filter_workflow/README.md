# ResearchMath Filter & Ranking Workflow

Score and rank open math research problems for AI-assisted investigation using Claude.

## Quick Start

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
python rank_problems.py --dataset researchmath_14k --limit 50
```

Results appear in `ranked_output/` as `.json` and `.csv` files.

## Files

| File | Purpose |
|------|---------|
| `workflow_guide.html` | **Open this first.** Full workflow documentation — open in browser, print to PDF. |
| `rank_problems.py` | Main scoring script. Calls Claude API to rate each problem on 5 dimensions. |
| `prompt_template.md` | The exact prompt sent to Claude (read to understand or customise scoring). |
| `config_example.yaml` | Configuration template — copy to `config.yaml` and edit. |
| `requirements.txt` | Python dependencies (`pip install -r requirements.txt`). |

## Datasets available

| Slug | Name | Size |
|------|------|------|
| `researchmath_14k` | ResearchMath-14k | 14,056 |
| `erdos_problems` | Erdős Problems | 1,217 |
| `aim_problem_lists` | AIM Problem Lists | 101 |
| `formal_conjectures` | Formal Conjectures (DeepMind) | 4,557 |
| `unsolved_math` | Unsolved Math | ~2,084 |

## Scoring dimensions

Each problem is scored 1–5 on:
- **Importance** (30%) — mathematical significance
- **AI Tractability** (25%) — amenable to AI exploration
- **Verifiability** (20%) — solution can be rigorously checked
- **Clarity** (15%) — precisely stated
- **Self-Containedness** (10%) — understandable without specific papers

## Cost estimate

~$0.20–0.40 per 100 problems with `claude-opus-4-8`.  
~$0.01–0.02 per 100 problems with `claude-haiku-4-5-20251001`.

## Browse problems first

Filter website: https://zipfile-legume-gaining.ngrok-free.dev/rmac/filter/  
Use the Insights tab for per-dataset statistics.
