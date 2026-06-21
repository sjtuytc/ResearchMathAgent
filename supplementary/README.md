# RMA Supplementary Material

System-details supplement for the ResearchMathAgent (RMA) self-evolving
mathematical-proof system, written in ACL format.

## Contents

| File | Description |
|------|-------------|
| `rma_supplementary.tex` | Source (ACL `\usepackage[preprint]{acl}`) |
| `rma_supplementary.pdf` | Compiled PDF (5 pages) |
| `acl.sty` | Official ACL style file (from acl-org/acl-style-files) |
| `acl_natbib.bst` | ACL bibliography style |

## Building

The `.tex` is self-contained with the bundled `acl.sty`. Compile with a
modern engine (Tectonic, XeLaTeX, or LuaLaTeX recommended for the fonts):

```bash
tectonic rma_supplementary.tex
```

## Scope

Documents the three execution channels (Claude Code / solver agent via
AnthropicVertex / push-forward single-shot), the issue-cycle pipeline
(critic → solver → verifier → expert meeting → synthesis), the document
system, caching layers, and the Claude Code vs. API vs. Vertex AI
clarification (Appendix I).
