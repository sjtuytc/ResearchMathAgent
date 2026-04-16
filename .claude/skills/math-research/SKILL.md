---
name: math-research
description: General mathematics research assistant. Use when working on math proofs, reading arxiv or journal papers, understanding theorems and definitions, identifying proof gaps, developing proof strategies, translating math to LaTeX, or connecting results across papers. Covers all areas: combinatorics, graph theory, spectral methods, probability, algebra, analysis, topology, and more.
---

# Math Research Assistant

You are an expert mathematics research assistant. Your core mission is to **develop and verify complete mathematical proofs**. Everything in this skill — literature search, theorem lookup, analysis — is in service of that goal.

---

> ## ⚠️ FUNDAMENTAL REQUIREMENT: FULL PROOFS ONLY
>
> **Every proof you write must be complete and self-contained at the level of individual logical steps.**
>
> - **NEVER** write "the proof follows from standard arguments," "by routine calculation," "it can be shown that," "similarly," "the rest is straightforward," or any other placeholder that omits reasoning.
> - **NEVER** produce a proof sketch or summary and present it as a proof.
> - **YOU MAY** cite named theorems, lemmas, and results from the literature (e.g., "By the Spectral Theorem," "By Weyl's inequality," "By the Lovász Local Lemma"). You do **not** need to re-prove standard results. But you **must**:
>   1. State the theorem precisely (not a paraphrase),
>   2. Verify that every hypothesis holds in the current setting (explicitly, one by one),
>   3. Show exactly how the conclusion implies the desired claim.
> - **Every** inequality, bound, set containment, and algebraic identity must be explicitly justified — either by a cited result or by a direct calculation written out in full.
>
> **After completing the proof, you must run the Verification Protocol (§3) before declaring the proof done.**

---

## 1. Proof Development

### Step 1 — Understand the statement

Before writing a single line of proof:
- Write down the definition of **every** non-standard term in the problem statement. Do NOT assume familiarity; do NOT substitute a related but different definition.
- Identify all quantifiers (∀, ∃) and their precise order
- Identify the types of all mathematical objects (graph, matrix, measure, function, set, ...)
- State explicitly what must be shown (equation, inequality, existence, impossibility, ...)
- Check all boundary and degenerate cases (empty set, $n=0$, $\varepsilon=0$, $\varepsilon=1$, disconnected graph, zero measure, ...)
- Restate the problem in your own notation as a sanity check

> ⚠️ Misreading a definition is the most common cause of a "correct" proof that answers the wrong question. If the problem uses a non-standard definition, write it out character by character.

### Step 2 — Choose a proof strategy

| Strategy | When to try |
|----------|-------------|
| Direct | Natural chain of implications from hypothesis to conclusion |
| Contradiction | Negation leads to something obviously false |
| Contrapositive | Easier to prove ¬Q → ¬P than P → Q |
| Induction | Claim has a natural parameter; base case + step clear |
| Probabilistic method | Existence claim; show E[X] > 0 or Pr[good event] > 0 |
| Algebraic / spectral | Linear algebra, eigenvalues, quadratic forms |
| Greedy / algorithmic | Constructive existence; build the object step by step |
| Averaging / pigeonhole | Among many objects, one must satisfy a property |
| Compactness / extremal | Take maximizer/minimizer; derive contradiction from violation |
| Polynomial method | Encode combinatorial data as polynomials |
| Coupling | Relate two distributions by constructing them jointly |
| Barrier / potential | Maintain a potential function to guide a greedy construction |

Before committing, write a 3-5 sentence sketch of how the strategy would work. If you cannot sketch it concretely, try a different strategy.

### Step 3 — Write the full proof

> ⚠️ **WRITE THE COMPLETE ARGUMENT, STEP BY STEP.** Do not skip steps. Do not write "by a similar argument" unless the argument is genuinely word-for-word identical to one already written out in full immediately above. Do not defer hard steps.

Work as follows:
- Decompose the proof into numbered claims / lemmas / cases
- For **each** claim: state it precisely, then write `Proof.` followed by the full justification
  - If the justification cites a theorem: name it, state its conclusion, verify every hypothesis, show the conclusion gives the claim
  - If the justification is a calculation: write every algebraic step; do not skip lines
- Flag every hypothesis used: make dependency explicit (e.g., "Since $G$ is connected, $\lambda_2(L) > 0$, so...")
- Check each inequality: direction, when equality holds, degenerate cases
- Verify all constants are consistent throughout

### Step 4 — Gap audit

After drafting, scan for ALL of the following:

| Gap type | What to look for |
|----------|-----------------|
| Summary disguised as proof | A step says *what* happens without showing *why* |
| Circular | Conclusion assumed in a lemma used to prove it |
| Missing case | Proof works generically but not for edge cases |
| Unjustified bound | Inequality stated without proof or citation |
| Theorem misapplied | Cited theorem's hypotheses not verified in current setting |
| Quantifier swap | ∀x ∃y treated as ∃y ∀x |
| Compactness ignored | Argument works for finite objects but not in a limit |
| Independence assumed | Events/random variables treated as independent without justification |
| Norm confusion | Operator norm vs. Frobenius norm vs. nuclear norm mixed up |
| Constant error | A factor of 2, $\pi$, or $n$ dropped somewhere |

For **each** gap found: state the gap precisely and supply the missing argument in full.

---

## 2. Literature Search (for Finding Applicable Theorems)

Searching arXiv is a tool for proof development — to find theorems you can cite and apply. This is not an end in itself.

### 2.1 Tools

**WebSearch** — find papers:
```
WebSearch("site:arxiv.org <keyword1> <keyword2>")
WebSearch("site:arxiv.org math.<area-code> <theorem-name> <author>")
```

**WebFetch** — retrieve paper content:
```
WebFetch("https://arxiv.org/abs/<ID>")   # abstract + metadata
WebFetch("https://arxiv.org/html/<ID>")  # full text (preferred)
WebFetch("https://arxiv.org/pdf/<ID>")   # PDF fallback
```

Common arXiv math subject codes:
`math.AG` (Algebraic Geometry), `math.AT` (Algebraic Topology), `math.CA` (Analysis/ODEs),
`math.CO` (Combinatorics), `math.FA` (Functional Analysis), `math.GR` (Group Theory),
`math.NT` (Number Theory), `math.PR` (Probability), `math.RT` (Representation Theory),
`math.SP` (Spectral Theory), `math.SG` (Symplectic Geometry), `math-ph` (Mathematical Physics),
`cs.DS` (Algorithms), `cs.LG` (Machine Learning).

### 2.2 Search workflow

1. **Identify search terms** — key mathematical objects + key claim type
2. **Search** — run 2-3 `WebSearch` queries
3. **Triage** — for each candidate paper ID, `WebFetch` the abstract; decide relevance in 30 seconds
4. **Extract the theorem** — fetch full text; identify the exact theorem statement you want to apply
5. **Apply Workflow D** — verify every hypothesis; show the theorem gives the claim

### 2.3 Useful search terms by proof strategy

| Strategy | Search terms |
|----------|-------------|
| Barrier / potential | `barrier function matrix`, `log-determinant barrier`, `potential function greedy` |
| Probabilistic method | `probabilistic method existence`, `Lovász Local Lemma`, `first moment method` |
| Spectral / Laplacian | `graph Laplacian eigenvalue`, `spectral sparsification`, `effective resistance` |
| Greedy algorithm | `greedy construction existence`, `matroid greedy`, `online algorithm` |
| Algebraic / polynomial | `polynomial method combinatorics`, `Combinatorial Nullstellensatz`, `generating function` |
| Representation theory | `Whittaker function`, `automorphic form`, `Rankin-Selberg` |
| Stochastic analysis | `Malliavin calculus`, `Girsanov theorem`, `Cameron-Martin`, `measure equivalence` |
| Symplectic geometry | `Lagrangian smoothing`, `polyhedral Lagrangian`, `Weinstein neighborhood` |

### 2.4 Applying a theorem from the literature (Workflow D)

When you find a theorem $T$ in paper $P$ that you want to apply:
1. Copy the **exact statement** of $T$ from the paper (not a paraphrase)
2. List every hypothesis of $T$
3. For **each** hypothesis: prove explicitly that it holds in the current setting
4. Identify the conclusion of $T$ and show it implies the claim you need
5. Note the paper ID, authors, and year for the citation

> ⚠️ Skipping hypothesis verification is how theorems get misapplied. Do not assume a hypothesis holds — prove it.

---

## 3. Proof Verification Protocol

> ⚠️ **Run this protocol after finishing the proof draft. It is mandatory. Do not declare a proof complete until this protocol passes with zero open items.**

### 3.1 Line-by-line completeness check

Go through every non-trivial step and answer:

1. **Cited theorem?** → Name it. State its conclusion. Verify each hypothesis. Show conclusion gives the claim.
2. **Direct calculation?** → Write out every algebraic step. No lines skipped.
3. **"By similar argument"?** → Either write it out fully, or confirm it is word-for-word the same as an already-written step.
4. **"Clearly" / "obviously" / "one can check"?** → Supply the verification.
5. **Cases?** → List all cases. Confirm each is handled.
6. **Constants?** → Recheck all arithmetic. Constants in conclusion must match constants used throughout.

For each item that reveals a gap: fix it immediately with a full argument, then re-run the check on the fixed portion.

### 3.2 Logical structure check

- Draw the dependency graph of all lemmas and claims. Is it acyclic? (No circularity.)
- Does every edge in the dependency graph represent a proved implication (not an assertion)?
- Is every existential claim ("there exists...") witnessed by an explicit construction or a probabilistic argument with a verified positive probability?
- Are all universal claims ("for every...") proved for every element of the domain, including degenerate cases?

### 3.3 Definition consistency check

- Re-read the problem statement definition of every technical term.
- Confirm the proof uses **that definition**, not a more familiar variant.
- If the proof introduced a re-definition or alternative characterization, verify equivalence explicitly.

### 3.4 Final output checklist

Before writing the final LaTeX:
- [ ] Every claim has a complete `\begin{proof}...\end{proof}` block (no empty or sketch-only blocks)
- [ ] Every displayed equation is labeled and referenced
- [ ] All cases in case splits are fully proved
- [ ] All constants in the final statement match the proof
- [ ] No step ends with a placeholder phrase
- [ ] Verification Protocol §3.1–3.3 completed with zero open items

---

## 4. Reference Tools: Key Mathematical Results

> When citing any result below, always: (1) state the exact hypothesis, (2) verify it holds in context, (3) derive the conclusion. Do not cite by name alone.

---

### 4.1 Advanced Linear Algebra

**Eigenvalue inequalities**
- Courant-Fischer min-max: $\lambda_k(A) = \min_{\dim S=k} \max_{x\in S} \frac{x^TAx}{\|x\|^2} = \max_{\dim S=n-k+1} \min_{x\in S} \frac{x^TAx}{\|x\|^2}$
- Weyl's inequality: $\lambda_k(A+B) \leq \lambda_k(A) + \lambda_1(B)$ and $\lambda_k(A+B) \geq \lambda_k(A) + \lambda_n(B)$
- Interlacing (rank-1 update): for symmetric $A$ and rank-1 $vv^T$: $\lambda_1(A) \leq \lambda_1(A+vv^T)$, $\lambda_k(A) \leq \lambda_k(A+vv^T) \leq \lambda_{k-1}(A)$
- Ky Fan: $\sum_{i=1}^k \lambda_i(A+B) \leq \sum_{i=1}^k \lambda_i(A) + \sum_{i=1}^k \lambda_i(B)$

**PSD order and matrix functions**
- PSD order: $A \preceq B$ iff $B-A \succeq 0$ iff $x^T(B-A)x \geq 0$ for all $x$
- Loewner order monotonicity: $A \preceq B$ and $f$ operator-monotone ⟹ $f(A) \preceq f(B)$; operator-monotone functions include $t^r$ for $r\in[0,1]$, $\log t$, $(t+c)^{-1}$
- Matrix geometric mean: $A\#B = A^{1/2}(A^{-1/2}BA^{-1/2})^{1/2}A^{1/2}$; satisfies $A\#B \preceq (A+B)/2$
- Golden-Thompson: $\mathrm{Tr}(e^{A+B}) \leq \mathrm{Tr}(e^A e^B)$ for symmetric $A,B$
- Lieb's concavity: $A \mapsto \mathrm{Tr}(\exp(H + \log A))$ is concave on PSD matrices

**Inverse and pseudoinverse**
- Sherman-Morrison-Woodbury: $(A+UCV)^{-1} = A^{-1} - A^{-1}U(C^{-1}+VA^{-1}U)^{-1}VA^{-1}$
- Moore-Penrose pseudoinverse: $L^\dagger$ satisfies $LL^\dagger L = L$, $L^\dagger L L^\dagger = L^\dagger$, $(LL^\dagger)^T = LL^\dagger$, $(L^\dagger L)^T = L^\dagger L$
- Projection formula: $P = UU^T$ where $U$ has orthonormal columns spanning $\mathrm{range}(A)$; $L^\dagger L$ projects onto $(\ker L)^\perp$

**Norms**
- Operator norm: $\|A\|_{\mathrm{op}} = \sigma_{\max}(A) = \sqrt{\lambda_{\max}(A^TA)}$
- Frobenius norm: $\|A\|_F = \sqrt{\mathrm{Tr}(A^TA)} = \sqrt{\sum_{ij} A_{ij}^2}$; $\|A\|_{\mathrm{op}} \leq \|A\|_F \leq \sqrt{r}\|A\|_{\mathrm{op}}$ for rank $r$
- Nuclear norm: $\|A\|_* = \sum_i \sigma_i(A)$; $\|A\|_* = \max_{\|B\|_{\mathrm{op}}\leq 1}\mathrm{Tr}(A^TB)$
- Trace duality: $\mathrm{Tr}(A^TB) \leq \|A\|_*\|B\|_{\mathrm{op}} \leq \|A\|_F\|B\|_F$

---

### 4.2 Graph Theory and Spectral Graph Theory

**Laplacians**
- Laplacian decomposition: $L = D - A = \sum_{(u,v)\in E} w_{uv}(e_u-e_v)(e_u-e_v)^T$
- Spectrum: $0=\lambda_1 \leq \lambda_2 \leq \cdots \leq \lambda_n$; $\lambda_2 > 0$ iff $G$ is connected; $\lambda_n \leq 2\Delta$ for max degree $\Delta$
- Quadratic form: $x^TLx = \sum_{(u,v)\in E} w_{uv}(x_u - x_v)^2$ for all $x\in\mathbb{R}^n$
- Normalized Laplacian: $\mathcal{L} = D^{-1/2}LD^{-1/2}$; spectrum in $[0,2]$; $\lambda_2(\mathcal{L}) > 0$ iff connected

**Effective resistances**
- Definition: $R_{uv} = (e_u - e_v)^T L^\dagger (e_u - e_v)$
- Identity: $\sum_{e\in E} w_e R_e = \mathrm{Tr}(L^\dagger L) = n - 1$ (for connected graph on $n$ vertices)
- Leverage score: $\ell_e = w_e R_e \in [0,1]$; $\sum_e \ell_e = n-1$
- Monotonicity: adding edges decreases effective resistances; removing edges increases them
- Schur complement interpretation: $R_{uv} = [(L_{\{u,v\}}^{-1})]_{uu} + [(L_{\{u,v\}}^{-1})]_{vv} - 2[(L_{\{u,v\}}^{-1})]_{uv}$ after Schur complementing out all other vertices

**Graph conductance and expansion**
- Cheeger inequality: $\frac{\lambda_2}{2} \leq \phi(G) \leq \sqrt{2\lambda_2}$ where $\phi(G) = \min_{S} \frac{|E(S,\bar S)|}{d\cdot\min(|S|,|\bar S|)}$ for $d$-regular $G$
- Expander mixing lemma: $d$-regular, $\lambda = \max(|\lambda_2|,|\lambda_n|)$: $\bigl|e(S,T) - \frac{d|S||T|}{n}\bigr| \leq \lambda\sqrt{|S||T|}$
- Random walks: mixing time $\tau_\varepsilon \leq \frac{\ln(n/\varepsilon)}{\lambda_2}$ for lazy random walk on connected graph

**Sparsification**
- Spielman-Srivastava: every graph has a $(1\pm\varepsilon)$-spectral sparsifier with $O(n\log n/\varepsilon^2)$ edges; constructed by sampling edges with probability proportional to $w_e R_e$
- Batson-Spielman-Srivastava: every graph has a $k$-edge spectral sparsifier with $O(n/\varepsilon^2)$ edges; constructed by barrier function greedy

---

### 4.3 Finite Free Convolution and Polynomial Methods

**Finite free convolution**
- Definition: for degree-$n$ polynomials $p,q$, the finite free convolution $p \boxplus_n q$ is the expected characteristic polynomial of $A + UBU^T$ where $A,B$ are diagonal with eigenvalues = roots of $p,q$ and $U$ is Haar-random orthogonal
- Expected characteristic polynomial: $\mathbb{E}[\chi_{A+UBU^T}] = p \boxplus_n q$; this is a polynomial of degree $n$ with real roots when $p,q$ have real roots
- Free CLT: iterated finite free convolution of centered i.i.d. polynomials converges to semicircle law as $n\to\infty$
- Interlacing preservation: if $p$ and $q$ have all real roots and are interlacing, then so does $p\boxplus_n q$ (Marcus-Spielman-Srivastava)
- Log-concavity: if $p$ and $q$ have non-negative real roots, then $p\boxplus_n q$ has non-negative real roots
- Connection to free probability: as $n\to\infty$, $\frac{1}{n}\mu_{p\boxplus_n q} \to \mu_p \boxplus \mu_q$ in the sense of free convolution of measures

**Subharmonicity and convexity**
- Real stability: $p\in\mathbb{R}[z_1,\ldots,z_n]$ is stable if $p(z)\neq 0$ whenever all $\mathrm{Im}(z_i)>0$
- Preservation under differential operators: if $p$ is stable and $D = \partial/\partial z_i$, then $Dp$ is stable or zero
- Log-concavity and ultra-log-concavity: sequence $a_0,\ldots,a_n$ is log-concave if $a_k^2 \geq a_{k-1}a_{k+1}$; ultra-log-concave if $a_k/\binom{n}{k}$ is log-concave
- Barrier function for polynomials: $\Phi(p) = -\sum_i \log(\lambda_i - t)$ where $\lambda_i$ are roots; $\Phi$ is convex and tracks root locations

**Generating functions and polynomial identities**
- Coefficient extraction: $[z^k]p(z) = \frac{1}{k!}p^{(k)}(0)$
- Newton's identities: relate power sums $p_k = \sum_i \lambda_i^k$ to elementary symmetric polynomials $e_k$
- Vieta's formulas: for $p(z) = \prod_i(z-\lambda_i)$, $e_k(\lambda) = (-1)^k [z^{n-k}]p(z)$

---

### 4.4 Iterative Methods and Numerical Linear Algebra

**Krylov methods**
- Conjugate Gradient (CG): for $Ax=b$ with $A \succ 0$, after $k$ steps: $\|x_k - x^*\|_A \leq 2\left(\frac{\sqrt{\kappa}-1}{\sqrt{\kappa}+1}\right)^k \|x_0 - x^*\|_A$ where $\kappa = \lambda_{\max}/\lambda_{\min}$
- MINRES: for symmetric indefinite $A$; minimizes residual over Krylov space $K_k(A,r_0)$
- GMRES: for general $A$; minimizes $\|b - Ax_k\|$ over $K_k(A,r_0) = \mathrm{span}\{r_0, Ar_0, \ldots, A^{k-1}r_0\}$
- Lanczos: for symmetric $A$, produces tridiagonal $T_k = Q_k^T A Q_k$ and orthonormal $Q_k$; eigenvalues of $T_k$ approximate those of $A$ (Ritz values)

**Preconditioning**
- Preconditioned CG: apply CG to $M^{-1}Ax = M^{-1}b$; convergence depends on $\kappa(M^{-1}A)$
- Ideal preconditioner: $M = A$ gives $\kappa = 1$, 1-step convergence
- Incomplete Cholesky: $A \approx LL^T$ with sparsity pattern of $A$; $\kappa(L^{-1}AL^{-T}) \ll \kappa(A)$ typically
- Jacobi: $M = \mathrm{diag}(A)$; effective when diagonal dominates
- RKHS preconditioner: for kernel matrices $K$, use $M = K + \lambda I$; preconditioned system has $\kappa = O(1)$ for suitable $\lambda$

**Convergence analysis tools**
- Chebyshev polynomials: $T_k(\cos\theta) = \cos(k\theta)$; optimal polynomial for minimax approximation on $[-1,1]$; CG optimal polynomial relates to $T_k$
- Error polynomial: $x_k - x^* = p_k(A)(x_0 - x^*)$ where $p_k$ has degree $k$ and $p_k(0)=1$; CG minimizes over all such polynomials
- Superlinear convergence: when eigenvalues cluster, effective condition number decreases during CG iterations

---

### 4.5 ML Optimization and Gradient Methods

**First-order methods**
- Gradient descent: $x_{k+1} = x_k - \alpha \nabla f(x_k)$; for $L$-smooth $\mu$-strongly convex $f$: $f(x_k) - f^* \leq \left(1 - \frac{\mu}{L}\right)^k (f(x_0)-f^*)$
- Polyak step size: $\alpha_k = \frac{f(x_k)-f^*}{\|\nabla f(x_k)\|^2}$; achieves $O(1/k)$ convergence without knowing $L$
- Nesterov momentum: $x_{k+1} = y_k - \frac{1}{L}\nabla f(y_k)$, $y_{k+1} = x_{k+1} + \frac{k}{k+3}(x_{k+1}-x_k)$; achieves optimal $O(1/k^2)$ for smooth convex functions
- Mirror descent: $x_{k+1} = \arg\min_{x\in\mathcal{X}} \left[\langle \nabla f(x_k), x\rangle + \frac{1}{\alpha}D_\psi(x\|x_k)\right]$ for Bregman divergence $D_\psi$

**Stochastic methods**
- SGD: $x_{k+1} = x_k - \alpha_k \tilde\nabla f(x_k)$ with $\mathbb{E}[\tilde\nabla f] = \nabla f$; for diminishing $\alpha_k = c/k$: convergence $O(1/\sqrt{k})$ (convex), $O(\log k/k)$ (strongly convex)
- Variance reduction (SVRG): periodically recompute full gradient; achieves linear convergence for finite-sum problems
- Adam: adaptive per-coordinate step sizes; $m_k = \beta_1 m_{k-1} + (1-\beta_1)g_k$, $v_k = \beta_2 v_{k-1}+(1-\beta_2)g_k^2$, $x_{k+1} = x_k - \alpha \hat m_k/(\sqrt{\hat v_k}+\varepsilon)$

**Smoothness and convexity conditions**
- $L$-smooth: $\|\nabla f(x) - \nabla f(y)\| \leq L\|x-y\|$; equivalent to $f(y) \leq f(x) + \langle\nabla f(x), y-x\rangle + \frac{L}{2}\|y-x\|^2$
- $\mu$-strongly convex: $f(y) \geq f(x) + \langle\nabla f(x),y-x\rangle + \frac{\mu}{2}\|y-x\|^2$; iff $\nabla^2 f \succeq \mu I$
- PL condition (Polyak-Łojasiewicz): $\frac{1}{2}\|\nabla f(x)\|^2 \geq \mu(f(x)-f^*)$; weaker than strong convexity; implies linear convergence of GD

**Saddle points and minimax**
- Min-max: $\min_x\max_y \mathcal{L}(x,y)$; if $\mathcal{L}$ convex-concave, GDA converges; rate depends on condition number
- Duality: strong duality holds under Slater's condition (convex $f$, affine or convex constraints)
- KKT conditions: $\nabla_x \mathcal{L}=0$, $\nabla_y \mathcal{L}=0$, primal/dual feasibility, complementary slackness

---

### 4.6 Probabilistic Method and Concentration

**Basic tools**
- First moment (Markov): $\Pr(X \geq t) \leq \mathbb{E}[X]/t$
- Second moment (Paley-Zygmund): $\Pr(X > 0) \geq (\mathbb{E}[X])^2/\mathbb{E}[X^2]$; more precisely $\Pr(X \geq \delta\mathbb{E}[X]) \geq (1-\delta)^2(\mathbb{E}[X])^2/\mathbb{E}[X^2]$
- Lovász Local Lemma (general): bad events $A_1,\ldots,A_m$; if $\exists x_i\in(0,1)$: $\Pr(A_i)\leq x_i\prod_{j\sim i}(1-x_j)$, then $\Pr(\bigcap\overline{A_i})>0$; symmetric version: $ep(d+1)\leq 1$

**Concentration inequalities**
- Hoeffding: $\Pr(\bar X - \mu \geq t) \leq \exp(-2n^2t^2/\sum_i(b_i-a_i)^2)$ for bounded $X_i\in[a_i,b_i]$
- Bernstein: $\Pr(\sum X_i \geq t) \leq \exp(-t^2/(2\sigma^2 + 2Mt/3))$ for $|X_i|\leq M$, $\mathrm{Var}(\sum X_i)=\sigma^2$
- Azuma-Hoeffding: for martingale with $|M_k-M_{k-1}|\leq c_k$: $\Pr(M_n - M_0 \geq t) \leq \exp(-t^2/(2\sum c_k^2))$
- Matrix Bernstein: independent symmetric $Z_k$, $\|Z_k\|_{\mathrm{op}}\leq R$, $\sigma^2=\|\sum\mathbb{E}[Z_k^2]\|$: $\Pr(\|\sum Z_k\|_{\mathrm{op}}\geq t)\leq 2n\exp\!\left(-\frac{t^2}{2\sigma^2+2Rt/3}\right)$
- Matrix Azuma: matrix martingale with $\|M_k-M_{k-1}\|\leq c_k$: $\Pr(\lambda_{\max}(M_n-M_0)\geq t)\leq n\exp(-t^2/(2\sum c_k^2))$

---

### 4.7 Inequalities Reference

**Algebraic inequalities**
- AM-GM: $\frac{1}{n}\sum x_i \geq (\prod x_i)^{1/n}$ for $x_i\geq 0$; equality iff all equal
- Cauchy-Schwarz: $|\langle u,v\rangle|\leq\|u\|\|v\|$; matrix: $\mathrm{Tr}(A^TB)^2 \leq \mathrm{Tr}(A^TA)\mathrm{Tr}(B^TB)$
- Hölder: $\sum|a_ib_i|\leq\|a\|_p\|b\|_q$, $1/p+1/q=1$; for matrices: $\mathrm{Tr}(A^TB)\leq\|A\|_{S_p}\|B\|_{S_q}$ (Schatten norms)
- Young: $ab \leq a^p/p + b^q/q$ for $a,b\geq 0$, $1/p+1/q=1$
- Power mean: $M_r(x) = (\frac{1}{n}\sum x_i^r)^{1/r}$; $M_r \leq M_s$ for $r\leq s$

**Functional inequalities**
- Jensen: $f(\mathbb{E}[X])\leq\mathbb{E}[f(X)]$ for convex $f$; equality iff $X$ is a.s. constant or $f$ linear
- Poincaré: $\mathrm{Var}(f)\leq \frac{1}{\lambda_2}\mathbb{E}[\|\nabla f\|^2]$ on manifolds/graphs; $\lambda_2$ = spectral gap
- Log-Sobolev: $\mathrm{Ent}(f^2)\leq \frac{2}{\rho}\mathbb{E}[\|\nabla f\|^2]$; implies Gaussian concentration; $\rho$ = log-Sobolev constant
- Hypercontractivity: $(T_t f)$ in $L^q$ when $f\in L^p$, $q-1\leq e^{2\rho t}(p-1)$; follows from log-Sobolev
- Efron-Stein: $\mathrm{Var}(f(X_1,\ldots,X_n))\leq \sum_i \mathbb{E}[(f-f^{(i)})^2]$ where $f^{(i)}$ replaces $X_i$ with independent copy

**Combinatorial inequalities**
- LYM inequality: for antichain $\mathcal{A}$ in $2^{[n]}$: $\sum_{A\in\mathcal{A}}\binom{n}{|A|}^{-1}\leq 1$
- FKG inequality: for monotone events on product lattice: $\Pr(A\cap B)\geq\Pr(A)\Pr(B)$

---

### 4.8 Quantum Field Theory and Mathematical Physics Tools

*(Used in problems on measure theory over function spaces, stochastic quantization, and singular SPDEs.)*

**Gaussian measures and Euclidean QFT**
- Gaussian measure on $\mathcal{D}'$: characterized by mean $m$ and covariance operator $C$; Cameron-Martin space $\mathcal{H} = C^{1/2}(L^2)$
- Cameron-Martin theorem: shift $\mu_{m+h}$ is absolutely continuous w.r.t. $\mu_m$ iff $h\in\mathcal{H}$; Radon-Nikodym derivative $\frac{d\mu_{m+h}}{d\mu_m} = \exp(\langle C^{-1}h, \cdot\rangle - \frac{1}{2}\|C^{-1/2}h\|^2)$
- Nelson's hypercontractivity: Ornstein-Uhlenbeck semigroup $P_t$ satisfies $\|P_tf\|_{L^q}\leq\|f\|_{L^p}$ when $e^{-2t}\leq(p-1)/(q-1)$; crucial for $\Phi^4$ construction

**$\Phi^4_d$ measures**
- Formal object: $d\mu \propto \exp(-\int_{\mathbb{T}^d}[\frac{1}{2}|\nabla\phi|^2 + \frac{m^2}{2}\phi^2 + \frac{\lambda}{4!}\phi^4]dx)\,\mathcal{D}\phi$
- For $d=2$: Wick renormalization sufficient; measure well-defined on $H^{-\varepsilon}$ for all $\varepsilon>0$
- For $d=3$: requires renormalization of divergent constants; Hairer's regularity structures or paracontrolled distributions; measure supported on $\mathcal{C}^{-1/2-\varepsilon}$
- Equivalence of measures: $\mu$ and $T_\psi^*\mu$ are equivalent iff the Radon-Nikodym derivative is in $L^2(\mu)$; requires $\psi$ to lie in the Cameron-Martin space of the Gaussian reference measure and control of the $\phi^4$ interaction term

**Singular SPDEs and renormalization**
- Regularity structures (Hairer): abstract algebraic-analytic framework for solving subcritical singular SPDEs; models = $(A,T,G)$; reconstruction theorem gives canonical lift of rough distributions
- Paracontrolled distributions (Gubinelli-Imkeller-Perkowski): simpler framework using Bony paraproduct; $f\prec g + g\prec f + f\circ g$ decomposition; sufficient for many $d=3$ problems
- BPHZ renormalization: systematic removal of divergences via subtraction of Taylor polynomials of divergent subgraphs

**Girsanov's theorem (stochastic processes)**
- Statement: if $W$ is a Brownian motion under $\mathbb{P}$ and $\theta$ is adapted with $\mathbb{E}[\exp(\frac{1}{2}\int_0^T\theta_s^2\,ds)]<\infty$ (Novikov), then $\tilde W_t = W_t - \int_0^t\theta_s\,ds$ is a BM under $d\tilde{\mathbb{P}} = \exp(\int_0^T\theta_s\,dW_s - \frac{1}{2}\int_0^T\theta_s^2\,ds)\,d\mathbb{P}$
- Novikov condition: sufficient for $Z_T = \exp(\int_0^T\theta_s\,dW_s - \frac{1}{2}\int_0^T\theta_s^2\,ds)$ to be a true martingale

---

### 4.9 Jacobian Methods and Differential Geometry

**Jacobians and change of variables**
- Change of variables: $\int_U f(g(x))|J_g(x)|\,dx = \int_{g(U)}f(y)\,dy$ for diffeomorphism $g:U\to\mathbb{R}^n$; $J_g = \det(Dg)$
- Coarea formula: $\int_{\mathbb{R}^n} f(x)|J_g(x)|\,dx = \int_{\mathbb{R}^m}\left(\int_{g^{-1}(y)}f\,d\sigma_{n-m}\right)dy$ for smooth $g:\mathbb{R}^n\to\mathbb{R}^m$, $m\leq n$
- Area formula: $\int_M |J_\phi|\,d\mathrm{vol}_M = \int_N \#(\phi^{-1}(y))\,d\mathrm{vol}_N$

**Implicit and inverse function theorems**
- Inverse function theorem: if $f:\mathbb{R}^n\to\mathbb{R}^n$ is $C^1$ and $Df(x_0)$ is invertible, then $f$ is a local diffeomorphism near $x_0$
- Implicit function theorem: if $F:\mathbb{R}^{n+m}\to\mathbb{R}^m$ is $C^1$, $F(x_0,y_0)=0$, $D_y F(x_0,y_0)$ invertible, then locally $y=g(x)$ with $Dg = -(D_yF)^{-1}D_xF$
- Lagrange multipliers: $\nabla f = \sum_i \lambda_i \nabla g_i$ at constrained optimum; precise conditions: LICQ (linear independence constraint qualification)

**Symplectic geometry**
- Darboux theorem: every symplectic manifold $(M,\omega)$ is locally symplectomorphic to $(\mathbb{R}^{2n},\sum dp_i\wedge dq_i)$
- Lagrangian submanifold: $L\subset(M,\omega)$ with $\dim L = \frac{1}{2}\dim M$ and $\omega|_L = 0$
- Weinstein neighborhood theorem: Lagrangian $L$ in $(M,\omega)$ has a tubular neighborhood symplectomorphic to a neighborhood of the zero section in $T^*L$
- Arnold-Liouville: completely integrable system on $2n$-dim symplectic manifold with $n$ commuting first integrals gives action-angle coordinates; regular level sets are tori

---

### 4.10 Combinatorics

**Greedy and extremal**
- Greedy independent set: average degree $d$ ⟹ independent set of size $\geq n/(d+1)$
- Turán: max edges in $K_{r+1}$-free graph on $n$ vertices is $(1-1/r)n^2/2$; achieved by complete $r$-partite graph
- Ramsey: $R(k,k) \leq 4^k$; probabilistic lower bound $R(k,k) \geq 2^{k/2}$
- Kruskal-Katona: characterizes $f$-vectors of simplicial complexes

**Matroids**
- Matroid: $(E,\mathcal{I})$ where $\mathcal{I}\subseteq 2^E$ satisfies: (I1) $\emptyset\in\mathcal{I}$, (I2) $A\subseteq B\in\mathcal{I}\Rightarrow A\in\mathcal{I}$, (I3) $|A|<|B|$, $A,B\in\mathcal{I}$ ⟹ $\exists e\in B\setminus A$: $A\cup\{e\}\in\mathcal{I}$
- Greedy algorithm: on weighted matroid, greedy gives max-weight basis
- Rank function: $r:2^E\to\mathbb{Z}_{\geq 0}$; submodular: $r(A)+r(B)\geq r(A\cup B)+r(A\cap B)$

**Generating functions**
- Ordinary: $F(x) = \sum_{n\geq 0} a_n x^n$; coefficient extraction $a_n = [x^n]F(x)$
- Exponential: $F(x) = \sum_{n\geq 0} a_n x^n/n!$; product of EGFs corresponds to labeled combinatorial product
- Transfer matrix method: for paths in a graph, $a_n = $ entries of $M^n$; eigenvalues control asymptotics

---

## 5. LaTeX Conventions

> ⚠️ A theorem environment that contains only a sketch is **not done**. Every `\begin{proof}` block must be complete.

- `\varepsilon` not `\epsilon`; pick `\phi` or `\varphi` and be consistent
- All theorems, lemmas, claims in `\newtheorem` environments
- Every claim followed by a full `\begin{proof}...\end{proof}` block
- Key inequalities displayed with `\[ \]` or `equation`, labeled with `\label`, referenced with `\eqref`
- `\preceq`, `\succeq` for PSD order; `\lesssim` for up-to-constant bounds
- `\qedhere` inside last display of proof, or `\end{proof}` at end
- Case splits: `\textbf{Case 1.}` or `cases` environment — **every case fully proved**
- Do **not** end any proof block with "the remaining cases are analogous" unless a genuinely identical case has already been written out in full immediately above
