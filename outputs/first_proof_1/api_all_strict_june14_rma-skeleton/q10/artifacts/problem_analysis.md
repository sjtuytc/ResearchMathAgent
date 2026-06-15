# Parsed Problem: q10

- Title: Problem 10: Preconditioned CG for RKHS-Constrained CP Decomposition
- Author: Tamara G. Kolda (MathSci.ai) and Rachel Ward (University of Texas at Austin)
- Area: numerical linear algebra and tensor decomposition
- Type: research problem
- Source input: `q10/input/problem.tex`

## Quantifiers
- No simple quantifier phrase was detected; preserve the statement's quantifier order.

## Definitions
- Let $N = \prod_i n_i$ denote the product of all sizes
- Let $n \equiv n_k$ be the size of mode $k$, let $M = \prod_{i\neq k} n_i$ be the product of all dimensions except $k$, and assume $n \ll M$
- let $q \ll N$ denote the number of observed entries
- let $T \in \mathbb{R}^{n \times M}$ denote the mode-$k$ unfolding of the tensor $\mathcal{T}$ with all missing entries set to zero

## Boundary Cases
- degenerate inputs allowed by the statement
