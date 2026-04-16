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

> ## ⚠️ CONSTRUCTION RULE
>
> **If the problem asks for a construction** ("Does there exist...", "Construct a...", "Find a...", "Show there exists..."), you must:
> 1. State the construction **explicitly and completely** — give the object in closed form or via a fully specified algorithm. Do not say "such an object exists" without producing it.
> 2. Place the construction either **at the very beginning** of the solution (before any proof) or **at the very end** as the conclusion. Do not bury it in the middle of the argument.
> 3. After giving the construction, prove it has all required properties — fully, with no steps omitted.

> ## ⚠️ CLEAN PROOF RULE
>
> **The final proof must contain only correct, complete arguments.**
>
> - If you discover mid-proof that a strategy or sub-argument is **wrong**, delete it entirely from the proof before continuing. Do not leave failed attempts, crossed-out steps, or "this approach doesn't work" commentary in the final output.
> - The final LaTeX file must read as if the correct proof was found on the first try: clean, linear, no dead ends, no wrong turns.
> - Wrong attempts are useful for your own reasoning, but must not appear in the submitted proof. Keep a mental scratch pad; only the final correct argument goes in the file.
> - If you revise a proof during the verify-and-revise rounds and a previous approach is superseded, remove all traces of the old approach.

> ## ⚠️ NO RETREAT POLICY: SOLVE THE FULL PROBLEM
>
> **You must attempt and deliver a proof of the full problem as stated. Partial solutions are not acceptable as final outputs.**
>
> - **NEVER** declare "this is an open research problem" and stop. The problems you are given ARE research-level — that is the point. Difficulty is not a reason to stop.
> - **NEVER** solve only a base case (e.g., $n=2$, $\varepsilon=1/2$, a specific graph family) and present it as the solution. Base cases may appear as intermediate steps, but the final proof must cover all cases in the problem statement.
> - **NEVER** solve a simplified or weakened version of the problem without explicitly proving the full version. Do not substitute an easier related problem.
> - **NEVER** write "the general case follows by similar methods" or "the full proof can be obtained by extending these ideas." Either write the full general proof or identify precisely what additional ingredient is missing — then go find it (search arXiv, try a different strategy).
> - **If you are stuck**: switch proof strategy (see Step 2 table), search arXiv for applicable theorems, try a probabilistic or algebraic approach, or decompose the problem into lemmas and attack each lemma fully. Exhaust multiple strategies before concluding anything is out of reach.
> - **If a sub-problem genuinely requires a new mathematical idea not yet in the literature**: state this explicitly, describe exactly what is missing and why, and provide the strongest partial result you can prove in full — but do not pretend partial = complete.

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

> ⚠️ **If your chosen strategy only handles a special case** (specific $n$, specific graph family, specific $\varepsilon$, etc.), do not stop there. Either extend the strategy to the general case, or combine it with a second strategy that handles the remaining cases. A strategy that only covers base cases is not a complete proof.

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

### Step 3b — Stuck protocol

If you reach a step you cannot prove:
1. **Re-examine the strategy** — is there a cleaner approach? Try at least 3 strategies from the Step 2 table before escalating.
2. **Search the literature** (§2) — the blocking step may be a known lemma. Search arXiv with precise terms.
3. **Decompose further** — if the step is too large, split it into 2-3 smaller claims and prove each.
4. **Try a weaker form** — prove a slightly weaker intermediate claim and check whether it still implies the main result.
5. **Only as a last resort** — if you have genuinely exhausted the above, state explicitly: (a) exactly what sub-claim is blocking, (b) why each strategy fails, (c) what new mathematical ingredient would be needed. Then provide the strongest complete partial result you can. **Do not present a partial result as the full solution.**

> ⚠️ "This is hard" or "this is a research problem" is never a stopping condition. Keep going.

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

### ⛔ BLOCKED PAPERS — DO NOT READ OR USE

The following URLs contain official solutions to the First Proof benchmark problems. **Reading them would constitute cheating.** You must not fetch, read, or use content from these papers in any form:

- `https://arxiv.org/html/2602.21201v1`
- `https://arxiv.org/abs/2602.05192`
- `https://arxiv.org/pdf/2602.21201` (PDF variant of the above)
- `https://arxiv.org/pdf/2602.05192` (PDF variant of the above)

More generally: **do not search for or read any paper that is explicitly described as a "solution" or "answer" to the First Proof benchmark.** If a search result or paper abstract mentions "First Proof" or the specific problem contributor's name in the context of a solution, skip it. You must derive the proof independently.

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

## 3. Proof Verification Protocol — Three Rounds of Verify-and-Revise

> ⚠️ **This protocol is mandatory. You must complete all three rounds before declaring the proof done. Each round consists of a full check followed by revision of every issue found. Do not skip rounds even if Round 1 finds no problems — a fresh pass often catches what the first misses.**

The structure is:
```
[Draft proof]
  → Round 1: Full check → Revise all issues → Updated proof
  → Round 2: Full check → Revise all issues → Updated proof
  → Round 3: Full check → Revise all issues → Final proof
```

After Round 3, if any open items remain, perform additional rounds until the proof is clean. Three rounds is the minimum, not the maximum.

---

### Round Template (repeat for Rounds 1, 2, and 3)

At the start of each round, write a heading: **"Verification Round N"**. Then run all four checks below in order. For every issue found, immediately write the fix in full, update the proof text, and note what was changed. Only move to the next check after all issues from the current check are resolved.

#### Check A — Line-by-line completeness

Go through every non-trivial step and answer:

1. **Cited theorem?** → Name it. State its conclusion exactly. Verify each hypothesis holds in the current setting (list them one by one). Show the conclusion gives exactly the claimed step.
2. **Direct calculation?** → Write out every algebraic/analytic step with no lines skipped.
3. **"By a similar argument" or "analogously"?** → Either write the argument in full, or confirm it is word-for-word identical to a step already written immediately above.
4. **"Clearly," "obviously," "one can check," "it follows that"?** → Supply the full verification.
5. **Cases?** → List every case explicitly. Confirm each one is fully handled, including all degenerate/boundary cases from Step 1.
6. **Constants?** → Recheck all numerical factors and arithmetic. Constants in the final conclusion must match those used throughout.
7. **Scope of generality?** → Confirm the proof covers the full generality of the problem statement — not just a base case, not just a special family. If the proof was written for a special case, extend it now.

**Action**: For each issue found in Check A, write the fix immediately, update the proof, and mark it resolved before proceeding to Check B.

#### Check B — Logical structure

- List all lemmas, claims, and sub-results used in the proof. Draw their dependency graph (can be written as a text list of "X uses Y").
- Is the graph acyclic? If any circularity exists, identify the cycle and break it by proving one of the steps from scratch.
- Does every edge represent a proved implication? Flag any edge that is merely asserted.
- Is every existential statement ("there exists $x$ such that...") either (a) witnessed by an explicit construction, or (b) proved by a probabilistic/non-constructive argument with a verified positive probability/count?
- Is every universal statement ("for all $x$...") proved for the entire domain, including $n=0$, $\varepsilon=0$, $\varepsilon=1$, empty sets, disconnected graphs, etc.?

**Action**: Fix every structural issue before proceeding to Check C.

#### Check C — Definition consistency

- Re-read the original problem statement word by word.
- For each technical term defined in the problem: confirm the proof uses that exact definition throughout. Write out the definition and point to each place it is used.
- If the proof introduced an alternative characterization or equivalent reformulation, verify the equivalence explicitly with a proof (not an assertion).
- If any step used a more familiar but subtly different definition (e.g., degree-threshold instead of spectral PSD condition), identify and correct it.

**Action**: Fix every definition inconsistency before proceeding to Check D.

#### Check D — Strength and completeness of the result

- Does the proof establish the full claim in the problem statement, or only a weaker version?
- If a weaker version was proved: identify exactly what is missing and attempt to strengthen it now.
- Are the constants optimal or at least matching what was claimed? Recheck all constant arithmetic end-to-end.
- Is the answer to the problem's binary question (Yes/No) clearly stated and supported by the proof?

**Action**: Strengthen the result if needed. If the full generality genuinely cannot be reached, document exactly what was proved and what remains open — but do not relabel a partial result as complete.

---

### Round 1 — First verification pass

*Run Checks A, B, C, D. Revise all issues. Write "Round 1 complete: [N issues found and fixed]."*

### Round 2 — Second verification pass

*Re-run Checks A, B, C, D on the revised proof. Common second-round catches: issues introduced by Round 1 fixes, constants that changed, new cases exposed by a broadened argument. Revise all issues. Write "Round 2 complete: [N issues found and fixed]."*

### Round 3 — Final verification pass

*Re-run Checks A, B, C, D on the twice-revised proof. This round should find zero or very few issues. Revise any remaining issues. Write "Round 3 complete: [N issues found and fixed]. Proof declared complete."*

---

### Final output checklist

Only after Round 3 passes cleanly:
- [ ] **Environment balance**: `\begin{proof}` count = `\end{proof}` count; all other environments balanced; no environment reaches `\end{document}` unclosed
- [ ] Every claim has a complete `\begin{proof}...\end{proof}` block (no empty or sketch-only blocks)
- [ ] Every displayed equation is labeled with `\label` and referenced with `\eqref`
- [ ] All cases in case splits are fully proved, including degenerate cases
- [ ] All constants in the final statement match constants used throughout the proof
- [ ] No step ends with a placeholder phrase
- [ ] Problem's full generality is covered (not just a base case or special family)
- [ ] Rounds 1, 2, and 3 each completed with all issues resolved
- [ ] Blocked papers were not consulted (§2 safeguard)

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
- Sard's theorem: the set of critical values of a $C^k$ map $f:\mathbb{R}^n\to\mathbb{R}^m$ (with $k>\max(n-m,0)$) has measure zero in $\mathbb{R}^m$; hence generic fibers are smooth manifolds
- Degree of a map: for smooth $f:M\to N$ between compact oriented $n$-manifolds, $\deg(f) = \sum_{x\in f^{-1}(y)}\mathrm{sign}(J_f(x))$ for regular value $y$; homotopy-invariant; $\deg(f\circ g) = \deg(f)\deg(g)$

**Implicit and inverse function theorems**
- Inverse function theorem: if $f:\mathbb{R}^n\to\mathbb{R}^n$ is $C^1$ and $Df(x_0)$ is invertible, then $f$ is a local diffeomorphism near $x_0$
- Implicit function theorem: if $F:\mathbb{R}^{n+m}\to\mathbb{R}^m$ is $C^1$, $F(x_0,y_0)=0$, $D_y F(x_0,y_0)$ invertible, then locally $y=g(x)$ with $Dg = -(D_yF)^{-1}D_xF$
- Constant rank theorem: if $\mathrm{rank}(Df)=r$ constant near $x_0$, then $f$ is locally equivalent to $(x_1,\ldots,x_n)\mapsto(x_1,\ldots,x_r,0,\ldots,0)$
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

### 4.11 Markov Chains

**Basic definitions and convergence**
- Discrete-time Markov chain: sequence $(X_n)$ with $\Pr(X_{n+1}=y\mid X_0,\ldots,X_n) = P(X_n,y)$ for transition matrix $P$; $P_{xy}\geq 0$, $\sum_y P_{xy}=1$
- Stationary distribution: $\pi P = \pi$ (i.e., $\pi(y) = \sum_x \pi(x)P(x,y)$); exists and is unique for irreducible finite chains
- Detailed balance (reversibility): $\pi(x)P(x,y) = \pi(y)P(y,x)$ for all $x,y$; implies $\pi$ is stationary; sufficient but not necessary
- Convergence: for irreducible aperiodic chain, $\|P^n(x,\cdot) - \pi\|_\mathrm{TV} \leq (1-\varepsilon)^n$ for some $\varepsilon>0$; rate controlled by spectral gap $1-\lambda_2(P)$

**Spectral theory of Markov chains**
- For reversible chain, $P$ is self-adjoint in $L^2(\pi)$: $\langle f, Pg\rangle_\pi = \langle Pf, g\rangle_\pi$; eigenvalues real in $[-1,1]$
- Spectral gap: $\gamma = 1 - \lambda_2$; mixing time $t_\mathrm{mix}(\varepsilon) \leq \frac{\ln(1/\varepsilon\pi_{\min})}{\gamma}$; Poincaré inequality: $\mathrm{Var}_\pi(f) \leq \frac{1}{\gamma}\mathcal{E}(f,f)$ where $\mathcal{E}(f,f)=\frac{1}{2}\sum_{x,y}\pi(x)P(x,y)(f(x)-f(y))^2$
- Cheeger constant: $\Phi = \min_{S:\pi(S)\leq 1/2}\frac{\sum_{x\in S,y\notin S}\pi(x)P(x,y)}{\pi(S)}$; Cheeger bound $\Phi^2/2 \leq \gamma \leq 2\Phi$

**Constructing Markov chains with prescribed stationary distribution**
- Metropolis-Hastings: proposal $Q(x,y)$; accept with probability $\min(1, \frac{\pi(y)Q(y,x)}{\pi(x)Q(x,y)})$; detailed balance holds by construction
- Gibbs sampler: for $\pi(x_1,\ldots,x_n)$, update one coordinate at a time from the conditional $\pi(x_i\mid x_{-i})$
- Proving stationarity via detailed balance: compute $\pi(x)P(x,y)$ and $\pi(y)P(y,x)$ and verify equality; for Macdonald-type chains, use ratio formula $\pi(\mu)/\pi(\nu) = F^*_\mu/F^*_\nu$ and check transitions match
- Coupling method: construct two copies of the chain starting from $x$ and $y$ on the same probability space; bound mixing time by $\mathbb{E}[\text{coupling time}]$

**Continuous-time Markov chains**
- Generator $Q$: $Q_{xy}\geq 0$ for $x\neq y$, $Q_{xx} = -\sum_{y\neq x}Q_{xy}$; semigroup $e^{tQ}$; stationary distribution satisfies $\pi Q = 0$
- Detailed balance: $\pi(x)Q(x,y) = \pi(y)Q(y,x)$; Dirichlet form $\mathcal{E}(f,f) = \frac{1}{2}\sum_{x\neq y}\pi(x)Q(x,y)(f(x)-f(y))^2$
- Relationship to discrete: $P = I + \frac{1}{\lambda_\max}Q$ gives a lazy chain with same stationary distribution

---

### 4.12 Construction Methods

**Probabilistic existence proofs**
- Basic probabilistic method: to show an object with property $\mathcal{P}$ exists, define a random object and show $\Pr(\mathcal{P}) > 0$; often via $\mathbb{E}[X]>0$ for some indicator $X$
- Alteration method: take a random object; deterministically remove elements causing failures; show enough remains; e.g., random graph $\to$ remove one vertex from each monochromatic clique
- Deletion method (for hypergraph coloring): sample each vertex independently; delete edges where all vertices same color; analyze remaining structure
- Algorithmic Lovász Local Lemma (Moser-Tardos): if LLL conditions hold, a random assignment satisfying all constraints can be found by the Moser-Tardos resampling algorithm in polynomial expected time

**Greedy and incremental constructions**
- Greedy: process elements in some order; include each if it does not violate the desired property; correctness requires showing the greedy choice never forecloses a feasible completion
- Augmenting path / flow: build a feasible object step by step; at each step, find an augmenting path to improve; terminates at optimum (max-flow min-cut)
- Barrier function greedy (Batson-Spielman-Srivastava style): maintain a PSD matrix $M\succ 0$; at each step find an element whose addition keeps $M$ feasible; feasibility tracked by a potential $\Phi(M) = \mathrm{Tr}((\alpha I - M)^{-1}) + \mathrm{Tr}((M - \beta I)^{-1})$; show potential stays bounded
- Inductive construction: build for $n$ assuming the result for $n-1$; ensure the inductive step works for all base configurations

**Algebraic / spectral constructions**
- Random matrix method: sample a random matrix with prescribed spectrum; show it witnesses the desired property with positive probability
- Polynomial construction: define a polynomial $p(x)$ whose roots encode the desired combinatorial object; use real stability or interlacing to control root locations
- Expander construction (algebraic): Cayley graph of a group with a symmetric generating set; Ramanujan graphs from number theory give optimal spectral gap
- Ultraproduct / compactness: if a property holds for all finite structures, use a compactness argument (Łoś's theorem for ultraproducts, or topological compactness) to obtain an infinite structure

**Geometric and topological constructions**
- Whitney embedding: every smooth $n$-manifold embeds in $\mathbb{R}^{2n}$; immersion in $\mathbb{R}^{2n-1}$
- Smoothing: given a PL or polyhedral object, produce a smooth one by local perturbation; existence often guaranteed by transversality
- Transversality theorem: generic smooth maps are transverse to a given submanifold; use to put two submanifolds in general position

---

### 4.13 Polynomial Maps

**Basic algebraic geometry**
- Variety: $V(I) = \{x\in k^n : f(x)=0\;\forall f\in I\}$ for ideal $I\subseteq k[x_1,\ldots,x_n]$; Zariski closed
- Dimension: $\dim V = $ transcendence degree of $k(V)/k$; for irreducible $V\subseteq\mathbb{A}^n$: $\dim V + \mathrm{codim}\,V = n$
- Morphism of varieties: $\phi:V\to W$ given by polynomial functions; fiber $\phi^{-1}(w)$ has dimension $\geq \dim V - \dim W$ (dimension of fibers inequality)
- Chevalley's theorem: image of a constructible set under a morphism is constructible (finite Boolean combination of locally closed sets)

**Polynomial maps and their images**
- Dominant map: $\phi:V\to W$ dominant if $\overline{\phi(V)} = W$; equivalent to generic fiber being finite for maps of the same dimension
- Generic fiber: for dominant $\phi:V\to W$ with $\dim V = \dim W$, the degree $\deg\phi = \#\phi^{-1}(w)$ for generic $w\in W$
- First Fundamental Theorem (FFT) of invariant theory: for $G$-action on $V$, the ring of invariants $k[V]^G$ is generated by explicit invariants (e.g., for $GL_n$ acting on matrices: traces $\mathrm{Tr}(A^k)$, determinants)
- Second Fundamental Theorem (SFT): relations among the generators of $k[V]^G$ are generated by explicit syzygies (e.g., Plücker relations for Grassmannians)

**Determinantal varieties and tensor maps**
- Determinantal variety: $M_r = \{A\in\mathrm{Mat}_{m\times n}(k) : \mathrm{rank}(A)\leq r\}$; defined by $(r+1)\times(r+1)$ minors; codimension $(m-r)(n-r)$; Cohen-Macaulay, normal
- Segre variety: image of $\mathbb{P}^m\times\mathbb{P}^n\to\mathbb{P}^{mn+m+n}$ via $(v,w)\mapsto v\otimes w$; the set of rank-1 matrices in $\mathrm{Mat}_{(m+1)\times(n+1)}$
- Veronese embedding: $\mathbb{P}^n\to\mathbb{P}^{\binom{n+d}{d}-1}$ by all degree-$d$ monomials; image is the $d$-th Veronese variety
- Resultant: $\mathrm{Res}(f,g) = 0$ iff $f$ and $g$ share a common root; computable as determinant of Sylvester matrix; degree $\deg g$ in coefficients of $f$
- Discriminant: $\Delta(f)=0$ iff $f$ has a repeated root; $\Delta(f) = \frac{(-1)^{n(n-1)/2}}{a_n}\mathrm{Res}(f,f')$ for $f$ of degree $n$ with leading coefficient $a_n$

**Polynomial interpolation and extension**
- Lagrange interpolation: unique polynomial of degree $\leq n$ through $n+1$ points; $p(x) = \sum_{i=0}^n y_i \prod_{j\neq i}\frac{x-x_j}{x_i-x_j}$
- Schwartz-Zippel lemma: if $p\in\mathbb{F}[x_1,\ldots,x_n]$ is nonzero of degree $d$, and $r_1,\ldots,r_n$ are chosen uniformly from $S\subseteq\mathbb{F}$, then $\Pr(p(r_1,\ldots,r_n)=0)\leq d/|S|$
- Combinatorial Nullstellensatz: if $\prod_{i=1}^n(x_i^{t_i+1})$ does not divide $p$ (with $\deg p = \sum t_i$) and the $x_1^{t_1}\cdots x_n^{t_n}$ coefficient of $p$ is nonzero, then for any $S_i\subseteq\mathbb{F}$ with $|S_i|=t_i+1$ there exist $s_i\in S_i$ with $p(s_1,\ldots,s_n)\neq 0$

---

### 4.14 Tensor Decomposition

**Basic tensor algebra**
- Tensor: element of $V_1\otimes\cdots\otimes V_k$ for vector spaces $V_i$; a $k$-way array of numbers after choosing bases; order $= k$, size $= n_1\times\cdots\times n_k$
- Rank-1 tensor: $a^{(1)}\otimes\cdots\otimes a^{(k)}$ with $a^{(i)}\in V_i$; mode-$i$ fiber $= a^{(1)}_{{j_1}}\cdots a^{(k)}_{j_k}$
- Tensor rank: $\mathrm{rank}(T) = \min r$ such that $T = \sum_{l=1}^r a^{(1)}_l\otimes\cdots\otimes a^{(k)}_l$; NP-hard to compute in general; $\mathrm{rank}(T)\leq n_1\cdots n_{k-1}$ trivially
- Border rank: $\underline{\mathrm{rank}}(T) = \min r$ such that $T$ is a limit of rank-$r$ tensors; $\underline{\mathrm{rank}}(T)\leq\mathrm{rank}(T)$; border rank of matrix multiplication $\langle m,n,p\rangle$ controls exponent of matrix multiplication

**CP decomposition (Canonical Polyadic / PARAFAC)**
- CP decomposition: $T = \sum_{r=1}^R \lambda_r\, a_r\otimes b_r\otimes c_r$ where $a_r\in\mathbb{R}^{I}$, $b_r\in\mathbb{R}^J$, $c_r\in\mathbb{R}^K$; $R$ = number of components
- Uniqueness (Kruskal's theorem): if $k_A + k_B + k_C \geq 2R+2$ where $k_X = $ k-rank (max $k$ s.t. every $k$ columns of $X$ are lin. indep.), then CP decomposition is unique up to permutation and scaling of components
- Jennrich's algorithm: for 3-way tensor with distinct factor matrices, simultaneous diagonalization of random linear combinations of frontal slices recovers factors
- Alternating Least Squares (ALS): fix all but one factor matrix; solve least squares for the remaining; repeat; convergence not guaranteed but widely used in practice

**Tucker decomposition**
- Tucker decomposition: $T = G\times_1 A^{(1)}\times_2 A^{(2)}\times_3 A^{(3)}$ where $G\in\mathbb{R}^{r_1\times r_2\times r_3}$ is core, $A^{(i)}\in\mathbb{R}^{n_i\times r_i}$ are factor matrices; multilinear rank $(r_1,r_2,r_3)$
- HOSVD (higher-order SVD): compute mode-$i$ unfolding $T_{(i)}$; take $A^{(i)}=$ top-$r_i$ left singular vectors; core $G = T\times_1 (A^{(1)})^T\times_2 (A^{(2)})^T\times_3 (A^{(3)})^T$; quasioptimal: $\|T-T_\mathrm{Tucker}\|_F \leq \sqrt{k}\,\sigma_{r+1}$ for $k$-th order tensor
- Mode unfolding: $T_{(i)}\in\mathbb{R}^{n_i\times(n_1\cdots n_{i-1}n_{i+1}\cdots n_k)}$; matricization of the tensor along mode $i$; $T_{(i)} = A^{(i)} G_{(i)} (A^{(k)}\otimes\cdots\otimes A^{(i+1)}\otimes A^{(i-1)}\otimes\cdots\otimes A^{(1)})^T$

**Symmetric tensors and Waring rank**
- Symmetric tensor: $T\in S^d V$ (totally symmetric); corresponds to a homogeneous polynomial $p\in k[x_1,\ldots,x_n]$ of degree $d$ via $T_{i_1\cdots i_d} = \frac{1}{d!}\partial_{x_{i_1}}\cdots\partial_{x_{i_d}}p(0)$
- Waring rank: min $r$ such that $p = \sum_{j=1}^r \ell_j^d$ for linear forms $\ell_j$; analogous to tensor rank; related to secant varieties of Veronese embedding
- Alexander-Hirschowitz theorem: the $r$-th secant variety of the $d$-th Veronese $V_{d,n}\subset\mathbb{P}^{\binom{n+d}{d}-1}$ has the expected dimension $\min(\binom{n+d}{d}-1, r(n+1)-1)$ except for finitely many exceptional cases
- Apolarity lemma: $\ell_1^d,\ldots,\ell_r^d$ are a Waring decomposition of $p$ iff $\{\ell_1,\ldots,\ell_r\}$ is the variety of the apolar ideal $p^\perp = \{q\in k[y_1,\ldots,y_n] : q(\partial)p = 0\}$

**Tensor networks and contractions**
- Contraction: $\sum_{i_k} T_{i_1\cdots i_k\cdots i_d}\cdot S_{j_1\cdots i_k\cdots j_e}$ sums over a shared index; generalizes matrix multiplication
- Matrix Product State (MPS) / Tensor Train: $T_{i_1\cdots i_n} = \sum_{\alpha_1,\ldots,\alpha_{n-1}} A^{(1)}_{i_1,\alpha_1} A^{(2)}_{\alpha_1,i_2,\alpha_2}\cdots A^{(n)}_{\alpha_{n-1},i_n}$; bond dimension $\chi$ controls expressivity; exact for states with area-law entanglement
- Trace of tensor network: contract all indices; cost determined by contraction order (treewidth of the network graph)

---

### 4.15 Abstract Algebra

**Groups**
- Group: $(G,\cdot)$ with associativity, identity $e$, inverses; order $|G|$; subgroup $H\leq G$; normal subgroup $N\trianglelefteq G$ iff $gNg^{-1}=N$ for all $g$
- Lagrange's theorem: $|H|$ divides $|G|$ for finite $G$; cosets partition $G$; $[G:H] = |G|/|H|$
- Homomorphism theorems: First: $G/\ker\phi \cong \mathrm{Im}(\phi)$; Second: $(HN)/N \cong H/(H\cap N)$; Third: $(G/N)/(M/N)\cong G/M$ for $N\leq M\leq G$
- Sylow theorems: for $|G|=p^a m$ with $p\nmid m$: (1) Sylow $p$-subgroups of order $p^a$ exist; (2) all Sylow $p$-subgroups are conjugate; (3) $n_p\equiv 1\pmod{p}$ and $n_p\mid m$
- Classification of finitely generated abelian groups: $\cong \mathbb{Z}^r \oplus \mathbb{Z}/d_1\mathbb{Z}\oplus\cdots\oplus\mathbb{Z}/d_k\mathbb{Z}$ with $d_1\mid d_2\mid\cdots\mid d_k$; $r$ = rank, $d_i$ = invariant factors

**Rings and modules**
- Ring: $(R,+,\cdot)$; commutative if $ab=ba$; unit $1$; ideal $I\subseteq R$ closed under $+$ and $R\cdot I\subseteq I$; quotient $R/I$
- PID (principal ideal domain): every ideal is principal; UFD; e.g., $\mathbb{Z}$, $k[x]$; over a PID, every submodule of a free module is free
- Noetherian ring: every ascending chain of ideals stabilizes; equivalently, every ideal is finitely generated; $k[x_1,\ldots,x_n]$ is Noetherian (Hilbert basis theorem)
- Module: abelian group $M$ with $R$-action $R\times M\to M$; free module $R^n$; projective: direct summand of free; injective: $\mathrm{Hom}(-,M)$ exact; flat: $M\otimes_R -$ exact
- Tensor product of modules: $M\otimes_R N$; universal property: bilinear maps $M\times N\to P$ = module maps $M\otimes_R N\to P$; right-exact; $\mathrm{Tor}_1^R(M,N)$ measures failure of left-exactness
- Exact sequences: $0\to A\to B\to C\to 0$ short exact; long exact sequence in homology from any short exact sequence of chain complexes

**Field theory and Galois theory**
- Field extension: $K/F$; degree $[K:F] = \dim_F K$; algebraic element: satisfies polynomial over $F$; minimal polynomial: monic irreducible generator of $\ker(\mathrm{ev}_\alpha: F[x]\to K)$
- Splitting field: smallest extension over which a polynomial splits into linear factors; unique up to isomorphism
- Galois group: $\mathrm{Gal}(K/F) = \{\sigma\in\mathrm{Aut}(K) : \sigma|_F = \mathrm{id}\}$; $|\mathrm{Gal}(K/F)| = [K:F]$ for Galois extensions (normal + separable)
- Fundamental theorem of Galois theory: bijection between subgroups $H\leq\mathrm{Gal}(K/F)$ and intermediate fields $F\subseteq E\subseteq K$: $H\mapsto K^H$, $E\mapsto\mathrm{Gal}(K/E)$; $H\trianglelefteq\mathrm{Gal}(K/F)$ iff $E/F$ Galois; then $\mathrm{Gal}(E/F)\cong\mathrm{Gal}(K/F)/H$
- Solvability by radicals: $f\in\mathbb{Q}[x]$ solvable by radicals iff $\mathrm{Gal}(f)$ is a solvable group

**Representation theory**
- Representation: group homomorphism $\rho:G\to GL(V)$; character $\chi_\rho(g) = \mathrm{Tr}(\rho(g))$; class function
- Maschke's theorem: for finite $G$ and $\mathrm{char}(k)\nmid|G|$, every representation decomposes as a direct sum of irreducibles
- Schur's lemma: any $G$-map between irreducible representations is 0 or an isomorphism; over $\mathbb{C}$, any endomorphism of an irreducible is scalar
- Character orthogonality: $\langle\chi_\rho,\chi_{\rho'}\rangle = \frac{1}{|G|}\sum_g\chi_\rho(g)\overline{\chi_{\rho'}(g)} = \delta_{\rho,\rho'}$ for irreducibles $\rho,\rho'$ over $\mathbb{C}$
- Number of irreducibles: equals number of conjugacy classes of $G$; $\sum_i (\dim\rho_i)^2 = |G|$
- Induced representation: $\mathrm{Ind}_H^G W = \mathbb{C}[G]\otimes_{\mathbb{C}[H]} W$; Frobenius reciprocity: $\langle\mathrm{Ind}_H^G W, V\rangle_G = \langle W, \mathrm{Res}_H^G V\rangle_H$

**Homological algebra**
- Chain complex: $(C_\bullet, d_\bullet)$ with $d_n:C_n\to C_{n-1}$ and $d_{n-1}\circ d_n = 0$; homology $H_n = \ker d_n / \mathrm{Im}\,d_{n+1}$
- Derived functors: $\mathrm{Ext}^n_R(M,N)$ = $n$-th derived functor of $\mathrm{Hom}_R(M,-)$; $\mathrm{Tor}_n^R(M,N)$ = $n$-th derived functor of $M\otimes_R -$; computed via projective/injective resolutions
- Five lemma: in a commutative diagram with exact rows $A\to B\to C\to D\to E$, if maps at $A,B,D,E$ are isos then map at $C$ is iso
- Spectral sequence: $(E_r^{p,q}, d_r)$ converging to $H^{p+q}$; Leray-Serre: for fibration $F\to E\to B$, $E_2^{p,q}=H^p(B;H^q(F))\Rightarrow H^{p+q}(E)$

## 5. LaTeX Conventions

> ⚠️ A theorem environment that contains only a sketch is **not done**. Every `\begin{proof}` block must be complete.

### 5.1 Environment balance — most critical rule

> ⛔ **Every `\begin{...}` must have a matching `\end{...}` before `\end{document}`.**  
> The error `\begin{proof} on input line N ended by \end{document}` means a proof block was never closed. This breaks the entire file.

**Mandatory environment-balance check** (do this before saving the file):
1. Count every `\begin{proof}` — count every `\end{proof}`. They must be equal.
2. Count every `\begin{theorem}` / `\begin{lemma}` / `\begin{claim}` / `\begin{corollary}` — count their matching `\end{...}`. All must be equal.
3. Count every `\begin{enumerate}` / `\begin{itemize}` / `\begin{align}` / `\begin{cases}` — all must be closed.
4. If any count is unequal, find the unclosed environment and close it with the correct `\end{...}` before proceeding.

**Common causes of unclosed proofs** — watch for these patterns:
- Writing `\begin{proof}` at the end of a section and forgetting `\end{proof}` before the next `\section{}`
- A `proof` environment that spans a long case split where one case's `\end{proof}` is accidentally omitted
- Copy-pasting a block that already contains `\begin{proof}` without its `\end{proof}`
- Nested environments where an inner `\end{proof}` is mistakenly used to close the outer one

### 5.2 General LaTeX rules

- `\varepsilon` not `\epsilon`; pick `\phi` or `\varphi` and be consistent throughout
- All theorems, lemmas, claims in `\newtheorem` environments; define them in the preamble
- Every claim followed by a full `\begin{proof}...\end{proof}` block — no block may end with a placeholder
- Key inequalities displayed with `\[ \]` or `equation` environment, labeled with `\label{eq:...}`, referenced with `\eqref{eq:...}`
- `\preceq`, `\succeq` for PSD order; `\lesssim` for up-to-constant bounds
- `\qedhere` inside the last displayed equation of a proof; `\end{proof}` on its own line at the end
- Case splits: `\textbf{Case 1.}` or `cases` environment — **every case fully proved before moving to the next**
- Do **not** end any proof block with "the remaining cases are analogous" unless an identical case has already been written out in full immediately above
- Always close: `align` → `\end{align}`, `itemize` → `\end{itemize}`, `enumerate` → `\end{enumerate}`, `figure` → `\end{figure}`, `table` → `\end{table}`
