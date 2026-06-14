# batch-2-AI-solutions

The AI-generated solutions to the ten batch-2 problems, de-anonymized. Each
problem has the four submissions, named by submitter (**A, B, C, D**) rather
than by the random animal codenames used during blind review.

## Layout

```
batch-2-AI-solutions/
  problem-01/ … problem-10/      one directory per problem
    submission-A.tex  submission-A.pdf
    submission-B.tex  submission-B.pdf
    submission-C.tex  submission-C.pdf
    submission-D.tex  submission-D.pdf
  README.md                      this file
```

The mapping from submission letter to the codenames used elsewhere (e.g. in
`../batch-2-anonymised-solutions/`) is recorded in that directory's
`hash-table.csv`.

## A note on standardization

These are **not** the verbatim model outputs: the LaTeX was standardized so that
every file is a clean, uniformly-formatted document that compiles with
`pdflatex`. The mathematics and prose are reproduced faithfully; the changes are
to formatting only:

- **Title block.** Each file carries a uniform title of the form
  `Submission <X> solution to Problem <n>` with an empty `\date{}`; the original,
  inconsistent title/author machinery was removed. (During blind review this
  title used the animal codename instead of the submission letter.)
- **Code-fence stripping.** Submission C's solutions were wrapped in a Markdown
  ```` ```latex ```` … ```` ``` ```` code fence; the wrapper lines were removed so
  the LaTeX inside compiles.
- **Markdown → LaTeX conversion.** Two of submission B's solutions
  (Problems 4 and 10) were authored as Markdown-with-LaTeX-math; they were
  converted to faithful, compiling LaTeX (headers → `\section*`/`\subsection*`,
  `**bold**` → `\textbf{}`, minimal preamble added). All math and prose are
  reproduced verbatim.

All 40 files compile cleanly with `pdflatex`, and the resulting PDFs are kept
alongside the sources.
