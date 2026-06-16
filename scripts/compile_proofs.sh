#!/usr/bin/env bash
# Compile all *_solution.tex files in the given experiment folder to PDF using tectonic.
# Usage: compile_proofs.sh [output_dir]
# Default output_dir: outputs/first_proof_1/verifyapi_june15_claude-code-sonnet

set -euo pipefail

TECTONIC="/projects/bhov/zzhao18/software/bin/tectonic"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/outputs/first_proof_1/verifyapi_june15_claude-code-sonnet}"

if [[ ! -f "$TECTONIC" ]]; then
  echo "ERROR: tectonic not found at $TECTONIC" >&2
  exit 1
fi

if [[ ! -d "$OUTPUT_DIR" ]]; then
  echo "ERROR: output dir not found: $OUTPUT_DIR" >&2
  exit 1
fi

shopt -s nullglob
TEX_FILES=("$OUTPUT_DIR"/*_solution.tex)

if [[ ${#TEX_FILES[@]} -eq 0 ]]; then
  echo "No *_solution.tex files found in $OUTPUT_DIR"
  exit 0
fi

echo "Compiling ${#TEX_FILES[@]} solution(s) in: $OUTPUT_DIR"
echo

PASS=0
FAIL=0
SKIP=0

for tex in "${TEX_FILES[@]}"; do
  base="$(basename "$tex" .tex)"
  pdf="$OUTPUT_DIR/${base}.pdf"

  # Skip if PDF is newer than source
  if [[ -f "$pdf" && "$pdf" -nt "$tex" ]]; then
    echo "  SKIP  $base.pdf (up to date)"
    (( SKIP++ )) || true
    continue
  fi

  # Validate minimal LaTeX structure before compiling
  if ! grep -q '\\begin{document}' "$tex" 2>/dev/null; then
    echo "  SKIP  $base.tex (no \\begin{document} — not valid LaTeX)"
    (( SKIP++ )) || true
    continue
  fi

  printf "  compiling %s ... " "$base"
  if "$TECTONIC" "$tex" --outdir "$OUTPUT_DIR" --keep-logs 2>/tmp/tectonic_last.log; then
    SIZE=$(du -h "$pdf" 2>/dev/null | cut -f1)
    echo "OK ($SIZE)"
    (( PASS++ )) || true
  else
    echo "FAIL"
    tail -5 /tmp/tectonic_last.log >&2 || true
    (( FAIL++ )) || true
  fi
done

echo
echo "Done: $PASS compiled, $SKIP skipped, $FAIL failed."
[[ $FAIL -eq 0 ]]
