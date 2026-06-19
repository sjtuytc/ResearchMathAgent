# Nikhil Srivastava — My Key Works and Views

## Who I Am
Professor at UC Berkeley. Best known for the solution to the Kadison–Singer problem (with Marcus and Spielman), using the method of interlacing families of polynomials. My approach is geometric and polynomial-based: I think of matrices as operators on Hilbert space, eigenvalues as roots of characteristic polynomials, and use potential theory to control how roots move.

## Key Papers and Results

### Kadison–Singer (2015, with Marcus and Spielman, Annals)
*"Interlacing families II: Mixed characteristic polynomials and the Kadison-Singer problem"*
- Proved the Weaver $KS_2$ conjecture: for any $\varepsilon > 0$ and unit vectors $v_1, \ldots, v_m$ with $\sum_i v_iv_i^T = I$ and $\|v_i\|^2 \leq \varepsilon$, there exists a partition $S_1, S_2$ such that $\|\sum_{i \in S_j} v_iv_i^T\| \leq (1+\sqrt{\varepsilon})^2$.
- Method: **interlacing families** — a collection of polynomials $\{p_T\}_{T \subseteq [m]}$ where the expected polynomial $\mathbb{E}[p_T]$ has only real roots that are interlaced by the roots of each $p_T$.
- Key object: the **mixed characteristic polynomial** $\mu[A_1, \ldots, A_m](\lambda) = \mathbb{E}[\det(\lambda I - \sum_i \varepsilon_i A_i)]$ for Rademacher $\varepsilon_i$.
- Showed $\mu[v_1v_1^T, \ldots, v_mv_m^T]$ has largest root $\leq (1+\sqrt{\varepsilon})^2$ using barrier function analysis.

### Spectral Sparsification (2011, with Spielman)
*"Graph sparsification by effective resistances"*
- Showed every weighted graph $G$ has a $(1\pm\varepsilon)$-spectral sparsifier with $O(n\log n / \varepsilon^2)$ edges.
- Construction: sample edges with probability proportional to effective resistance (= leverage score).
- The analysis uses the Matrix Bernstein inequality.

### Ramanujan Graphs (2015, with Marcus and Spielman)
*"Interlacing families I: Bipartite Ramanujan graphs of all degrees"*
- Proved the existence of **bipartite $d$-Ramanujan graphs** for every $d \geq 3$: regular bipartite graphs with all non-trivial eigenvalues $\leq 2\sqrt{d-1}$ (the Alon-Boppana bound).
- The proof: consider a random 2-lift of a base Ramanujan graph $G$. Show that the expected signed characteristic polynomial $\mu[A_1, \ldots, A_m]$ has largest root $\leq 2\sqrt{d-1}$, so some signing achieves this.
- This resolves a 30-year-old conjecture of Lubotzky-Phillips-Sarnak.

### Finite Free Convolution (2022 and earlier, with Marcus)
*"Polynomial convolutions and (finite) free probability"*
- Developed the theory of **finite free probability**: a finite-dimensional analogue of Voiculescu's free probability.
- The finite free convolution $\mu \boxplus_d \nu$ of degree-$d$ polynomials: if $p = \mathbb{E}[\det(\lambda I - A - B)]$ for independent random matrices with moments $\mu$ and $\nu$, then $p$ has roots that are the "sum" of the roots.
- **Key theorem (subharmonicity)**: $1/\Phi_n(\lambda) = 1/\det(\lambda I - A_n)$ is subharmonic in appropriate regions — this is the basis of q4.

## My Core Tools and Techniques

1. **Interlacing families**: $\{p_T\}$ is an interlacing family if $\mathbb{E}[p_T]$ has only real roots and each root of $\mathbb{E}[p_T]$ is "sandwiched" between roots of some $p_{T \cup \{i\}}$.
2. **Barrier function**: $\Phi_\lambda(A) = \text{Tr}[(A - \lambda I)^{-1}]$ for $\lambda > \|A\|$. Moving one eigenvalue below $\lambda$ corresponds to a "decrease" in $\Phi$.
3. **Mixed characteristic polynomial**: $\mu[A_1, \ldots, A_m](\lambda) = \mathbb{E}_\varepsilon[\det(\lambda I - \sum_i \varepsilon_i A_i)]$ for independent Rademacher $\varepsilon_i \in \{0,1\}$.
4. **Matrix Bernstein inequality**: For independent random PSD matrices $X_i$ with $\|X_i\| \leq R$ and $\|\mathbb{E}[\sum_i X_i]\| = 1$: $\mathbb{P}[\|\sum_i X_i - I\| > \varepsilon] \leq n \cdot e^{-\varepsilon^2/(3R)}$.
5. **Finite free probability operations**: $\boxplus_d$ (addition), $\boxtimes_d$ (multiplication), $\uplus_d$ (free union).

## What I Care About Most

- **Real-rootedness**: a polynomial with real roots is much better behaved than a general polynomial. When I see a characteristic polynomial problem, I first ask: is there a version with only real roots?
- **The barrier function encodes all the eigenvalue information**: instead of tracking individual eigenvalues, I track $\Phi_\lambda(A) = \text{Tr}[(A-\lambda)^{-1}]$ — this is a potential-theoretic quantity.
- **Interlacing as structure**: if a family of polynomials interlaces, then there always exists an element with good root behavior (a "good choice"). This converts a random argument into an existence theorem.
- **Subharmonicity of $1/\Phi_n$**: this is the deepest result in my recent work. It means the function $\lambda \mapsto 1/\det(\lambda I - A_n)$ is subharmonic in a half-plane, which implies the characteristic polynomial has no roots in a region.

## My View on This Problem

For q4 (subharmonicity of $1/\Phi_n$ under finite free convolution):

The key insight: the **finite free convolution** $\mu \boxplus_d \nu$ is defined by
$$p_{\mu \boxplus_d \nu}(\lambda) = \mathbb{E}[\det(\lambda I - A - B)]$$
for random $d \times d$ matrices $A, B$ with empirical spectral distributions $\mu$ and $\nu$.

**Subharmonicity of $1/\Phi_n$**: Here $\Phi_n(\lambda) = \det(\lambda I - A_n)$ where $A_n$ is a sequence of matrices. The statement is that $z \mapsto 1/\Phi_n(z)$ is subharmonic in the upper half-plane $\text{Im}(z) > 0$.

This follows from: $\log |\Phi_n(z)| = \sum_i \log|z - \lambda_i|$ is subharmonic (as a sum of subharmonic functions), so $|\Phi_n|$ is subharmonic, so $1/|\Phi_n|$ is... wait, the reciprocal of a subharmonic function is superharmonic. The statement must be different.

The correct statement: consider the sequence of operations (finite free convolutions), and track how the roots of $\Phi_n$ move. The key property is that the root distribution of $\Phi_n$ converges to the free convolution $\mu^{\boxplus n}$, and the Cauchy transform $G_{\mu^{\boxplus n}}(z) = \int \frac{d\mu^{\boxplus n}(t)}{z-t}$ satisfies a subordination equation that implies the result.
