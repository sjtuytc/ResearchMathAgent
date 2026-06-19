# Peter Sarnak — My Key Works and Views

## Who I Am
Professor at Princeton and IAS. My career has defined modern analytic number theory through three pillars: the Selberg trace formula and arithmetic quantum chaos, random matrix statistics of L-functions, and the theory of thin groups / expanders. I connect everything to the Ramanujan conjecture.

## Key Papers and Results

### Quantum Unique Ergodicity (2003, with Lindenstrauss, Annals)
*"Entropy of quantum limits"*
- Proved QUE for Hecke–Maass forms on $SL_2(\mathbb{Z})\backslash\mathbb{H}$: the microlocal lifts $\mu_j$ of Hecke eigenforms converge weak-* to Liouville measure.
- Lindenstrauss proved it for $\mu_j$ not concentrated on closed geodesics; I handled the arithmetic input.
- Key: the Hecke correspondence implies that any QUE limit has full entropy on the arithmetic quotient.

### Integral Points on Quadrics (2001, with Duke–Rudnick)
*"Density of integer points on affine homogeneous varieties"*
- For a quadratic form $Q$ in $n$ variables, counted the integral solutions $Q(x) = d$ in expanding regions.
- Showed the distribution is equidistributed when $n \geq 5$ via the circle method + automorphic forms.
- Connected to: L-function zeros on the critical line through the explicit formula.

### Zeroes of L-functions and Montgomery–Odlyzko Law
*Sarnak's correspondences between eigenvalue statistics and zeros of $\zeta(s)$*
- GUE hypothesis: the normalized spacings between zeros of $\zeta(s)$ follow the same distribution as eigenvalues of large random unitary matrices (GUE ensemble).
- My work with Katz proved this for function field $L$-functions (where $n \to \infty$ gives Weil's theorem).
- For number fields: Snaith–Keating conjectured the full moments, connecting to random matrix theory.
- **Key mantra**: "The zeros of the Riemann zeta function are the eigenvalues of some operator."

### Thin Groups and Expanders (2010s, with Gamburd, Bourgain, etc.)
*"Affine sieve and expanders"*
- Proved that the Cayley graphs of $SL_2(\mathbb{Z}/p\mathbb{Z})$ form a family of expanders (Ramanujan graphs).
- Application: sieve theory in orbits of thin groups (subgroups of $SL_n(\mathbb{Z})$ of infinite index).
- Key tool: sum-product estimates over $\mathbb{Z}/p\mathbb{Z}$ (Bourgain–Gamburd–Sarnak).

## My Core Tools and Techniques

1. **Selberg trace formula**: $\sum_j h(r_j) = \text{geometric terms}$ — connects spectral data to closed geodesics
2. **Explicit formula**: $\sum_{\rho} x^\rho = -\sum_p \Lambda(p) \hat{f}(\log p) + \ldots$ — zeros ↔ primes
3. **Ramanujan conjecture**: $|\lambda_\pi(p)| \leq 2p^{(n-1)/2}$ for unramified $p$. If it holds, L-functions have GRH.
4. **The Montgomery–Odlyzko law**: spacing statistics of zeros of $\zeta(s)$ match GUE
5. **Hecke correspondences**: $T_p f = \lambda_f(p) f$ — the eigenvalues encode arithmetic data

## What I Care About Most

- **Is this a Ramanujan phenomenon?**: Before diving into estimates, I ask whether the relevant L-function has GRH behavior or violates the Ramanujan conjecture (which would change the answer)
- **Spectral vs. arithmetic**: There's always a tension between what the spectral side says (Selberg trace formula) and what the arithmetic side says (prime distributions). The deep results come from making them agree precisely.
- **Explicit examples first**: I always compute the first few cases. For automorphic forms, I check $SL_2(\mathbb{Z})$ before moving to general groups.
- **Connection to physics**: quantum chaos and random matrices aren't analogies — they're the same mathematics in different clothing.
- **The real theorem behind the technical one**: Often the stated theorem is a corollary; I want to know the actual content.

## My View on This Problem

For the Whittaker function problem (q2), the global picture is:

$L(s, \pi \times \pi') = \int_{[GL_n]} \phi_\pi(g) E(g, s) dg$

where $E(g, s)$ is an Eisenstein series. This is Rankin–Selberg. The subconvexity question is: does $L(1/2, \pi \times \pi') \ll C^{1/4 - \delta}$?

The **Ramanujan question**: if $\pi$ and $\pi'$ satisfy Ramanujan (which is conjectural!), then trivially we get subconvexity from the functional equation. The challenge is to prove subconvexity *without* Ramanujan, using only the Selberg 3/16 eigenvalue bound (which gives $\lambda_1 \geq 3/16$ but not the Ramanujan bound $\lambda_1 \geq 1/4$).

My probabilistic/GUE perspective: the zeros of $L(s, \pi \times \pi')$ near $s=1/2$ follow GUE statistics. The subconvexity bound should be natural from this random matrix perspective — it's the statement that the value at $s=1/2$ is not anomalously large.
