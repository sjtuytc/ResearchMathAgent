# Parsed Problem: q6

- Title: Problem 6: $\varepsilon$-Light Subsets in Graphs
- Author: Daniel Spielman (Yale University)
- Area: spectral graph theory
- Type: existence
- Source input: `q6/input/problem.tex`

## Quantifiers
- Universal quantifier detected: the proof must cover every admissible input.
- Existential quantifier detected: the proof must construct or certify an object.

## Definitions
- let $G_S = (V, E(S,S))$ denote the graph with the same vertex set, but only the edges between vertices in $S$
- Let $L$ be the Laplacian matrix of $G$ and let $L_S$ be the Laplacian of $G_S$
- I say that a set of vertices $S$ is $\epsilon$-light if the matrix $\epsilon L - L_S$ is positive semidefinite

## Boundary Cases
- $\varepsilon=0$
- $\varepsilon=1$
- empty graph
- single-vertex graph
- disconnected graph
- singular matrix
- zero-dimensional boundary case
