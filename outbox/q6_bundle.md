# Research Collaboration Bundle — Problem 6 (Spielman, ε-Light Subsets)
*Send this entire document to Claude. Ask Claude to follow the WORKFLOW section.*

---

## 0. INSTRUCTIONS FOR YOUR FRIEND

Hi! Please paste this full document into Claude and say:

> "Please follow the WORKFLOW at the end of this document exactly, producing all requested deliverables."

Enable extended thinking if you can (Claude Pro → "Extended thinking" toggle). Then copy **the complete Claude response** and send it back to me.

---

## 1. PROBLEM STATEMENT

**Source:** First Proof Benchmark, Problem 6 (Daniel Spielman, Yale).

For a graph $G = (V, E)$, let $G_S = (V, E(S,S))$ denote the graph with the same vertex set but only the edges between vertices in $S$. Let $L$ be the Laplacian of $G$ and $L_S$ the Laplacian of $G_S$.

**Definition.** $S \subseteq V$ is *ε-light* if $\varepsilon L - L_S \succeq 0$.

**Question.** Does there exist a constant $c > 0$ such that for every graph $G$ and every $\varepsilon \in [0,1]$, the vertex set $V$ contains an $\varepsilon$-light subset $S$ of size at least $c\varepsilon |V|$?

**Answer:** YES. The best known explicit constant is $c = 1/42$ (Spielman). The conjectured tight constant is $c = 1/2$ (analogy with edge-sparsification / Kadison–Singer).

---

## 2. NOTATION

- $L^\dagger$: Moore–Penrose pseudoinverse of $L$.
- $L^{\dagger/2}$: PSD square root of $L^\dagger$.
- $\widetilde{L}_S := L^{\dagger/2} L_S L^{\dagger/2}$, similarly $\widetilde{L}_{S,t} := L^{\dagger/2} L_{S,\{t\}} L^{\dagger/2}$.
- $\Pi$: orthogonal projector onto $\mathrm{im}(L)$.
- $\ell(s,t) := w(s,t)(\delta_s - \delta_t)^\top L^\dagger (\delta_s - \delta_t)$: leverage score of edge $(s,t)$.
- $\ell(S) := \ell(S, V \setminus S)$: boundary leverage of $S$.
- For symmetric $A'$ and PSD $N$: **symmetrized Tr-σ convention**: $\mathrm{Tr}_\sigma(A'N) := \mathrm{Tr}_\sigma(N^{1/2} A' N^{1/2})$.
- Barrier: $\mathcal{B}^u_\sigma(A) := \sum_{i=1}^\sigma \frac{1}{u - \lambda_i}$ (top-σ resolvent sum, $= \infty$ if $u \leq \lambda_1$).
- Parameters: $\delta := 21/n$, $\phi := n/21$, $\sigma := \lfloor \varepsilon n / 42 \rfloor$.

---

## 3. PROOF OUTLINE (CURRENT BEST ATTEMPT, c = 1/42)

Build $S$ greedily: start with a single vertex $v_0$ with low boundary leverage ($\ell(\{v_0\}) \leq 4$), set $u_0 = \varepsilon/2$. At each step, find $t \notin S$ such that both the leverage invariant and the barrier invariant are maintained when we add $t$. After $\sigma$ steps $|S| = \sigma + 1$, and by the rank bound for $L_S$ and parameter choices, $\|\widetilde{L}_S\|_\mathrm{op} \leq u_\sigma \leq \varepsilon$, establishing $\varepsilon L \succeq L_S$.

**The two key steps:**
- **Step 3 (Leverage averaging):** More than half the candidates $t \notin S$ satisfy $\ell(t, V \setminus S) \leq 4$. Proof: average leverage is $< 2$ by Foster's identity; Markov at threshold 4.
- **Step 4 (Barrier averaging):** More than half the candidates $t \notin S$ satisfy $U(S,t) < 1$, where

$$U(S,t) := \frac{\mathrm{Tr}_\sigma(M^{-2} \widetilde{L}_{S,t})}{\mathcal{B}^u_\sigma(S) - \mathcal{B}^{u+\delta}_\sigma(S)} + \mathrm{Tr}_\sigma(M^{-1} \widetilde{L}_{S,t})$$

with $M = (u+\delta)I - \widetilde{L}_S$.

Proof: show $\sum_{t \notin S} U(S,t) \leq 5/\delta + 5\phi$; then Markov at threshold 1 gives $|\mathcal{B}| > m/2$.

---

## 4. CURRENT PROOF OF STEP 4 (THE CRITICAL SECTION)

The proof uses the following key identity and lemmas.

**Block decomposition of $M^p$** ($p \in \{-1,-2\}$):

Let $\Pi_S$ project onto $\mathrm{im}(\widetilde{L}_S)$, $\Pi_S^\perp = I - \Pi_S$. Since $\widetilde{L}_S \Pi_S = \widetilde{L}_S$ and $M\Pi_S = \Pi_S M$, the matrix $M^p$ leaves both subspaces invariant, and on $\ker \widetilde{L}_S$ it acts as $(u+\delta)^p I$:

$$M^p = (u+\delta)^p \Pi_S^\perp + \Pi_S M^p \Pi_S, \quad p \in \{-1,-2\}.$$

**Application of Ky Fan subadditivity (eq. split):**

Using the symmetrized convention:

$$\mathrm{Tr}_\sigma(M^p \widetilde{L}_{S,t}) := \mathrm{Tr}_\sigma(\widetilde{L}_{S,t}^{1/2} M^p \widetilde{L}_{S,t}^{1/2})$$

Substituting the block decomposition, the right-hand side splits as a sum of two PSD matrices:

$$\widetilde{L}_{S,t}^{1/2}[(u+\delta)^p \Pi_S^\perp]\widetilde{L}_{S,t}^{1/2} + \widetilde{L}_{S,t}^{1/2}[\Pi_S M^p \Pi_S]\widetilde{L}_{S,t}^{1/2}$$

Both summands are PSD (conjugation of PSD matrices by $\widetilde{L}_{S,t}^{1/2}$). Apply Ky Fan subadditivity $\mathrm{Tr}_\sigma(A+B) \leq \mathrm{Tr}_\sigma(A) + \mathrm{Tr}_\sigma(B)$ to these **symmetric PSD** matrices to get:

$$\mathrm{Tr}_\sigma(M^p \widetilde{L}_{S,t}) \leq \mathrm{Tr}_\sigma((u+\delta)^p \Pi_S^\perp \widetilde{L}_{S,t}) + \mathrm{Tr}_\sigma((\Pi_S M^p \Pi_S)\widetilde{L}_{S,t}) \quad \text{(split)}$$

(Here the right-hand side terms are still written in the symmetrized convention, which is well-defined for symmetric $A'$ and PSD $N$.)

**$\Pi_S^\perp$ piece:** $\mathrm{Tr}_\sigma(\Pi_S^\perp \widetilde{L}_{S,t}) \leq \mathrm{Tr}(\widetilde{L}_{S,t}) = \ell(S,t)$, so summing: $\sum_{t \notin S} \mathrm{Tr}_\sigma((u+\delta)^p \Pi_S^\perp \widetilde{L}_{S,t}) \leq (u+\delta)^p \ell(S) \leq (u+\delta)^p \cdot 4|S|$.

**$\Pi_S$ piece:** Using $\mathrm{Tr}_\sigma(A \widetilde{L}_{S,t}) \leq \mathrm{Tr}(A \widetilde{L}_{S,t})$ for PSD $A$, and $\sum_{t \notin S} \widetilde{L}_{S,t} = \widetilde{L}_{S,V\setminus S} \preceq \Pi$, we get $\sum_{t \notin S} \mathrm{Tr}((\Pi_S M^p \Pi_S)\widetilde{L}_{S,t}) \leq \mathrm{Tr}(\Pi_S M^p \Pi_S)$.

Then by the **Ky Fan maximum principle** (variational form): since $\Pi_S$ has rank $\leq |S|-1 \leq \sigma-1$, and $M^p \succeq 0$:

$$\mathrm{Tr}(\Pi_S M^p \Pi_S) \leq \mathrm{Tr}_\sigma(M^p).$$

Combining: $\sum_{t \notin S} \mathrm{Tr}_\sigma(M^p \widetilde{L}_{S,t}) \leq 4|S|(u+\delta)^p + \mathrm{Tr}_\sigma(M^p) \leq 5 \mathrm{Tr}_\sigma(M^p)$ (using $|S| \leq \sigma$ and $(u+\delta)^p \geq 0$).

Then use $\mathcal{B}^u_\sigma(S) - \mathcal{B}^{u+\delta}_\sigma(S) \geq \delta \cdot \mathrm{Tr}_\sigma(M^{-2})$ to bound the denominator, giving $\sum_{t \notin S} U(S,t) \leq 5/\delta + 5\phi$.

---

## 5. OPEN ISSUE (the one remaining mathematical question)

**Title:** Ky Fan subadditivity applied to non-Hermitian product in eq. (split)

**Description:**

The application of Ky Fan subadditivity in eq. (split) requires careful justification. The theorem $\mathrm{Tr}_\sigma(A+B) \leq \mathrm{Tr}_\sigma(A) + \mathrm{Tr}_\sigma(B)$ applies to **Hermitian** matrices $A, B$.

In the current proof, after introducing the symmetrized convention $\mathrm{Tr}_\sigma(M^p \widetilde{L}_{S,t}) := \mathrm{Tr}_\sigma(\widetilde{L}_{S,t}^{1/2} M^p \widetilde{L}_{S,t}^{1/2})$, the block decomposition gives:

$$\mathrm{Tr}_\sigma(\widetilde{L}_{S,t}^{1/2} M^p \widetilde{L}_{S,t}^{1/2}) = \mathrm{Tr}_\sigma(\underbrace{(u+\delta)^p \widetilde{L}_{S,t}^{1/2} \Pi_S^\perp \widetilde{L}_{S,t}^{1/2}}_{=: A_t} + \underbrace{\widetilde{L}_{S,t}^{1/2} (\Pi_S M^p \Pi_S) \widetilde{L}_{S,t}^{1/2}}_{=: B_t})$$

$A_t$ and $B_t$ are both **symmetric PSD** (conjugations of PSD matrices by $\widetilde{L}_{S,t}^{1/2}$). So Ky Fan subadditivity **does** apply to $A_t + B_t$.

But the resulting bound writes:
$$\mathrm{Tr}_\sigma(A_t + B_t) \leq \mathrm{Tr}_\sigma(A_t) + \mathrm{Tr}_\sigma(B_t)$$

and then **re-expresses** $\mathrm{Tr}_\sigma(A_t)$ as $\mathrm{Tr}_\sigma((u+\delta)^p \Pi_S^\perp \widetilde{L}_{S,t})$ (applying the symmetrized convention in reverse). The question is: **is this re-expression valid?**

Specifically: does $\mathrm{Tr}_\sigma(\widetilde{L}_{S,t}^{1/2} [(u+\delta)^p \Pi_S^\perp] \widetilde{L}_{S,t}^{1/2}) = \mathrm{Tr}_\sigma((u+\delta)^p \Pi_S^\perp \widetilde{L}_{S,t})$ under the symmetrized convention? Yes — by definition of the convention, $\mathrm{Tr}_\sigma((u+\delta)^p \Pi_S^\perp, \widetilde{L}_{S,t}) := \mathrm{Tr}_\sigma(\widetilde{L}_{S,t}^{1/2} (u+\delta)^p \Pi_S^\perp \widetilde{L}_{S,t}^{1/2})$. So this is consistent.

**The remaining question:** After this bound on $\mathrm{Tr}_\sigma(A_t)$, the proof then bounds:
$$\mathrm{Tr}_\sigma(\Pi_S^\perp \widetilde{L}_{S,t}) \leq \mathrm{Tr}(\Pi_S^\perp \widetilde{L}_{S,t}) \leq \mathrm{Tr}(\widetilde{L}_{S,t}) = \ell(S,t).$$

The step $\mathrm{Tr}_\sigma(X) \leq \mathrm{Tr}(X)$ for PSD $X$ is standard. The step $\mathrm{Tr}(\Pi_S^\perp \widetilde{L}_{S,t}) \leq \mathrm{Tr}(\widetilde{L}_{S,t})$ follows from $\Pi_S^\perp \preceq I$ and $\widetilde{L}_{S,t} \succeq 0$, which gives $\mathrm{Tr}((\Pi_S^\perp - I)\widetilde{L}_{S,t}) \leq 0$. **Is this step explicitly justified in the proof?** It needs to be.

---

## 6. BACKGROUND ON THE CONSTANT 1/42

The constant 1/42 comes from choosing $\delta = 21/n$ and $\phi = n/21$, which balances $5/\delta + 5\phi = 5n/21 + 5n/21 = 10n/21$. The Markov step then gives fraction $\leq (10n/21) / (41n/42) = 20/41 < 1/2$.

To improve $c$, you need $\delta \cdot (5/\delta + 5\phi) / n < 1/2$, i.e., $(5 + 5\phi\delta)/n < 1/2$. With $\phi\delta$ fixed (it only depends on the "5 × 5" factor), the current proof gives $c = 1/42$. Any improvement to the constants (e.g., getting "4 + 4" instead of "5 + 5" in the sum) would improve $c$.

The key constants are:
- "4" in the leverage invariant: $\ell(S) \leq 4|S|$ (comes from average leverage $< 2$, Markov at 4)
- "5" coefficient in $\sum_{t \notin S} U(S,t) \leq 5/\delta + 5\phi$: comes from $4|S| + 1 \leq 5\sigma$

---

## 7. WORKFLOW (follow these steps in order)

### Task A: Verify the Proof

1. Carefully read the proof of Step 4 in Section 4 above.
2. Determine whether the Ky Fan subadditivity application in eq. (split) is **fully justified** given the symmetrized Tr-σ convention.
3. Specifically check: is the step $\mathrm{Tr}(\Pi_S^\perp \widetilde{L}_{S,t}) \leq \mathrm{Tr}(\widetilde{L}_{S,t})$ justified, and is it made explicit in the proof?
4. Are there any other gaps or unjustified steps in Section 4?
5. Give a verdict: **RESOLVED** (the proof is complete and correct) or **STILL OPEN** (describe exactly what is missing).

### Task B: Fix Any Remaining Gaps

If Task A found gaps:
1. Write the exact LaTeX text that fixes each gap.
2. Make the fix minimal — do not restructure the proof, just add the missing argument.

### Task C: Attempt to Improve the Constant

1. Analyze where the constant 1/42 comes from (see Section 6).
2. Can the leverage threshold of 4 be tightened? (The average is $< 2$; Markov at threshold $2 + \epsilon$ for some $\epsilon$?)
3. Can the "5 + 5" coefficient be reduced? Where does each "5" come from?
4. Is there a modification of the greedy step or the barrier argument that achieves $c > 1/42$?
5. If you can achieve a better constant with a clean proof, present it. If not, explain the obstruction.

### Task D: Clean Final LaTeX

Write a clean, self-contained LaTeX section (just the proof body, no document preamble) that:
- Incorporates the fix from Task B (if any)
- Uses the same notation as Section 2 above
- Is ready for submission-quality write-up

---

## 8. EXPECTED OUTPUT FORMAT

Please structure your response exactly as follows so I can parse it programmatically:

```
=== TASK_A_VERDICT ===
[RESOLVED or STILL_OPEN]
[Explanation — which steps are correct, which (if any) are incomplete]
=== END_TASK_A ===

=== TASK_B_FIX ===
[LaTeX text for the fix, or "No fix needed" if RESOLVED]
=== END_TASK_B ===

=== TASK_C_CONSTANT ===
[Analysis of the constant. If improved: state new c and proof sketch. If not: explain obstruction.]
=== END_TASK_C ===

=== TASK_D_PROOF ===
[Full clean LaTeX proof of Step 4 (barrier averaging), incorporating any fixes]
=== END_TASK_D ===

=== TASK_D_ISSUES_JSON ===
[A JSON array of any new issues found, formatted as:
[{"title": "...", "body": "...", "severity": "critical|major|minor"}]
Or [] if no new issues.]
=== END_TASK_D_ISSUES_JSON ===
```

---

*End of bundle. Thank you!*
