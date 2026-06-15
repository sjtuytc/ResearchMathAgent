# test-dummy

Test submission for the First Proof shared compute pipeline.

Reads `/data/input/input.json` (a list of LaTeX math problems),
sends each problem to an LLM via OpenRouter (using the
`openrouter/free` router, which picks any available free model),
and writes `.tex` files to
`/data/output/` with the LLM response wrapped in a `verbatim`
block so the output always compiles.

Requires `OPENROUTER_API_KEY` in the secrets file.
Runs on `t3.micro`.
