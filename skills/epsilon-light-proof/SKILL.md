---
name: epsilon-light-proof
description: Research assistant for the epsilon-light subset problem in spectral graph theory. Use when working on, verifying, or extending the proof that every graph G=(V,E) and every epsilon in [0,1] has an epsilon-light subset S of size >= c*epsilon*|V| for some universal constant c > 0. Helps develop proof strategies, check logical gaps, analyze examples, compare approaches (greedy/random/barrier), and write LaTeX solutions.
---

# Epsilon-Light Subset Research Skill

You are assisting with active research on the following open problem in spectral graph theory.

## Problem Statement

**Definition.** Let $G = (V, E, w)$ be a (weighted) graph on $n$ vertices. For $S \subseteq V$, let $G_S$ be the subgraph containing all vertices but only edges with *both* endpoints in $S$. Let $L$ and $L_S$ be the Laplacians of $G$ and $G_S$ respectively.

A subset $S \subseteq V$ is **$\varepsilon$-light** if $L_S \preceq \varepsilon L$ (i.e., $\varepsilon L - L_S$ is positive semidefinite).

**Question.** Does there exist an absolute constant $c > 0$ such that for every graph $G$ and every $\varepsilon \in [0,1]$, there exists an $\varepsilon$-light subset $S \subseteq V$ with $|S| \geq c \varepsilon |V|$?

**Answer: Yes.** The best known constant is $c = 1/42$ (Spielman), and the tight bound is conjectured to be $c = 1/2$ (forced by $K_{n/2, n/2}$).

## Key Facts You Must Know

### Spectral reformulation
$L_S \preceq \varepsilon L$ is equivalent to:
$$\forall x \in \mathbb{R}^n: \sum_{(u,v) \in E(S,S)} (x_u - x_v)^2 \leq \varepsilon \sum_{(u,v) \in E} (x_u - x_v)^2$$

### Trivial observations
- Any independent set $I$ satisfies $L_I = 0 \preceq \varepsilon L$ for all $\varepsilon \geq 0$
- $S = V$ is $1$-light
- Any single vertex is $\varepsilon$-light for all $\varepsilon$

### Leverage scores
The **leverage score** (effective resistance) of edge $(s,t)$ is:
$$\ell(s,t) = w(s,t) \cdot (\delta_s - \delta_t)^T L^\dagger (\delta_s - \delta_t) = \text{Tr}(\tilde{L}_{\{s\},\{t\}})$$
where $\tilde{L}_S = L^{\dagger/2} L_S L^{\dagger/2}$. Key property: $\sum_{(s,t) \in E} \ell(s,t) = \text{rank}(L) \leq n-1$.

### Tight example: $K_{n/2, n/2}$
For $\varepsilon \in [0,1)$, every $\varepsilon$-light set is "pure" (contained in one side $A$ or $B$). The maximum size is $n/2$. Since $n/2 \geq c\varepsilon n$ requires $c \leq 1/(2\varepsilon)$, taking $\varepsilon \to 1^-$ forces $c \leq 1/2$.

## Proof Approaches

### Approach 1: Greedy Independent Set (sparse case)
- **When**: $d_{\text{avg}} \leq 1/(2\varepsilon)$
- **Method**: Greedy independent set; any graph with avg degree $d$ has independent set of size $\geq n/(d+1)$
- **Result**: $|I| \geq n/(d_{\text{avg}}+1) \geq \varepsilon n / (1 + 2\varepsilon) \geq \varepsilon n / 3$
- **Limitation**: Only works in the sparse regime

### Approach 2: Random Sampling (dense case)
- **When**: $d_{\text{avg}} > 1/(2\varepsilon)$
- **Method**: Include each vertex in $S$ independently with probability $p = \sqrt{\varepsilon}$
- **Key calculation**: $\mathbb{E}[L_S] = p^2 L = \varepsilon L$; $\mathbb{E}[|S|] = \sqrt{\varepsilon} n \geq \varepsilon n$
- **Concentration**: Use Matrix Azuma inequality (Tropp 2012) for PSD condition; Paley-Zygmund for size
- **Result**: With positive probability, both $|S| \geq \varepsilon n / 2$ and $L_S \preceq 2\varepsilon L$
- **Limitation**: Bound degrades with $d_{\max}$; gives roughly $c = 1/4$

### Approach 3: Spielman's Barrier Function (optimal known)
This achieves $c = 1/42$ and works for all graphs uniformly.

**Setup**: Work with $\tilde{L}_S = L^{\dagger/2} L_S L^{\dagger/2}$. The goal becomes $\tilde{L}_S \preceq \varepsilon I$.

**Parameters**:
$$\delta = \frac{21}{n}, \quad \phi = \frac{n}{21}, \quad \sigma = \lfloor \varepsilon n / 42 \rfloor$$

**Modified BSS barrier** (upper barrier on top $\sigma$ eigenvalues):
$$\Phi_\sigma^u(A) = \sum_{i=1}^\sigma \frac{1}{u - \lambda_i(A)}$$

**Greedy construction**: Start with $S_0 = \{v_0\}$, $u_0 = \varepsilon/2$. Repeatedly add vertex $t \notin S$ that:
1. Keeps $\Phi_\sigma^{u+\delta}(S \cup \{t\}) \leq \phi$ (barrier condition)
2. Keeps $\ell(S \cup \{t\}) \leq \ell(S) + 4$ (leverage score condition)

**Key inductive lemma**: If $|S| \leq \sigma$, $\ell(S) \leq 4|S|$, and $\Phi_\sigma^u(S) \leq \phi$, then such a vertex $t$ exists. (Proved by showing each condition holds for $> n/2$ choices of $t$, so their intersection is non-empty.)

**Final bound**: After $\sigma$ steps, the barrier gives $\tilde{L}_S \preceq (u_0 + \sigma\delta)I = \varepsilon I$, so $L_S \preceq \varepsilon L$ and $|S| = \sigma + 1 > \varepsilon n / 42$.

## How to Help the User

### When asked to verify a proof step
1. Check the mathematical claim carefully against the definitions
2. Identify which approach (sparse/dense/barrier) is being used
3. Point out gaps: missing cases, unjustified bounds, circular reasoning
4. Suggest fixes with precise calculations

### When asked to improve the constant
- The gap between $c = 1/42$ (Spielman) and $c = 1/2$ (conjectured tight) is wide
- Key open question: Can the barrier function approach be tightened to $c = 1/2$?
- Alternative: Can the random approach (Approach 2) be made to work without the $d_{\max}$ dependence?

### When writing LaTeX
- Use `\varepsilon` (not `\epsilon`) consistently
- Include the spectral reformulation as a quadratic form
- State the main theorem, then proof by cases (sparse/dense)
- Reference Tropp 2012 for Matrix Azuma, BSS12 for the barrier technique

### When analyzing a new example graph
1. Compute the Laplacian $L$
2. Check if the graph is sparse ($d_{\text{avg}} \leq 1/(2\varepsilon)$) or dense
3. Find candidate $\varepsilon$-light sets (independent sets, one side of bipartition, etc.)
4. Verify the PSD condition $L_S \preceq \varepsilon L$ using the quadratic form

### When asked about the conjecture $c = 1/2$
- The $K_{n/2,n/2}$ example shows this is tight if true
- The conjecture would say: every graph has an $\varepsilon$-light set of size $\varepsilon n / 2$
- Possible approach: adaptive $p = \varepsilon$ in random sampling with a tighter analysis
- Possible approach: modify Spielman's parameters ($\delta, \phi, \sigma$) to push constant toward $1/2$

## Files in This Project

- `problem.tex` — the problem statement (English + Chinese)
- `Claude_solution.tex` — Claude's proof sketch (achieves $c = 1/4$ sketch, conjectures $c = 1/2$)
- `true_answer.tex` — Spielman's rigorous proof achieving $c = 1/42$
- `gemni_solution.tex` — Gemini's solution attempt
- `background.tex` — Background material, examples, and context
- `ai_assignments/` — AI agent assignments directory

## Key References

- **BSS12**: Batson, Spielman, Srivastava — "Twice-Ramanujan Sparsifiers" (origin of the barrier technique)
- **Tropp 2012**: "User-Friendly Tail Bounds for Sums of Random Matrices" (Matrix Azuma inequality)
- **Spielman-Srivastava 2011**: "Graph Sparsification by Effective Resistances"
- **de la Peña-Giné**: *Decoupling: From Dependence to Independence* (U-statistics decoupling)
