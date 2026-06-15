# Documents

Daily reports and other markdown documents surfaced by the web app's
**Documents** tab.

- The autonomous daily worker (`python -m webapp.daily`) writes a dated report
  here each day, e.g. `2026-06-15.md`.
- On-demand runs ("Generate today's report" in the Documents tab) append to the
  same day's report.

Generated reports (`*.md` other than this README) are gitignored by default —
they are machine-generated and server-local. Commit one explicitly if you want
to keep it in version control.
