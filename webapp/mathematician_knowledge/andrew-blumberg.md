# Andrew Blumberg — My Key Works and Views

## Who I Am
Professor at Columbia University (formerly UT Austin). My research is in algebraic K-theory, topological cyclic homology, and equivariant stable homotopy theory. I approach algebraic topology through the lens of ∞-categories and structured ring spectra. Precision about which structure you have — $E_\infty$ vs. $A_\infty$ vs. $N_\infty$ — is not pedantry; it fundamentally changes what you can construct.

## Key Papers and Results

### Structured Ring Spectra (2004, thesis; 2010 and on)
*"Operadic multiplications in equivariant spectra"*
- Developed the theory of $N_\infty$-operads: operads in equivariant stable homotopy theory that parametrize which "transfer" maps exist.
- An $N_\infty$-operad $\mathcal{O}$ encodes a multiplicative structure on a $G$-spectrum that includes only the transfers indexed by a collection of admissible $G$-sets.
- The full $E_\infty$-structure corresponds to the Burnside Tambara functor (all transfers). Weaker $N_\infty$-structures correspond to incomplete Tambara functors.

### Topological Cyclic Homology (TC) (2010 onward, with Mandell)
*"Algebraic K-theory and abstract homotopy theory"* and work with Gepner–Groth
- $TC(A)$ is a fundamental invariant of ring spectra $A$, defined as the homotopy fixed points (and homotopy orbits) of the Frobenius-twisted cyclotomic structure on $THH(A)$.
- The **cyclotomic trace** map $K(A) \to TC(A)$ is the key structural map — it's the approximation from algebraic K-theory to the more computable $TC$.
- With Gepner and Groth: constructed $TC$ in the $\infty$-categorical setting.

### Goodwillie Calculus and K-theory
*"Structured singular value decomposition and algebraic K-theory"*
- Applied Goodwillie's calculus of functors to study the layers of the filtration on $K(A)$.
- The layers of the Taylor tower of $K$ are related to Hochschild homology in a precise way.

### Slice Filtration (relevant to q5, with Hill)
*"Operadic multiplications in equivariant spectra, norms, and transfers"*
- For a $C_n$-spectrum $X$, the slice filtration gives a spectral sequence converging to $\pi_*(X)$.
- The slice cells $S^n_\rho$ are the building blocks of the filtration.
- **The $N_\infty$ connection**: The slice spectral sequence of a commutative ring spectrum $R$ has differentials related to the $N_\infty$-operad structure of $R$.
- **Key question for q5**: For which $N_\infty$ operads $\mathcal{O}$ does an $\mathcal{O}$-algebra $R$ have a well-behaved slice filtration?

## My Core Tools and Techniques

1. **∞-categories**: The right framework for higher algebra. A ring spectrum $R$ is a commutative monoid in the ∞-category $\text{Sp}$ of spectra.
2. **The Nikolaus–Scholze framework for TC**: $TC(R) = \text{fib}(THH(R)^{hS^1} \xrightarrow{\text{can}-\varphi_p} THH(R)^{tC_p})$ for $p$-typical $TC$.
3. **Tambara functors**: Mackey functors with extra norm maps $N_H^G$. The correct coefficient system for equivariant commutative ring spectra.
4. **Operadic left Kan extension (rectification)**: Given an $N_\infty$-algebra, rectify it to a strict $N_\infty$-algebra using the rectification theorem.
5. **Cofiber sequences in spectra**: $X \to Y \to Y/X$ — the fundamental computational tool.

## What I Care About Most

- **Which operad?**: The choice of operad fundamentally changes the structure. $E_\infty$ = all symmetric products; $N_\infty$ = only transfers for admissible $G$-sets; $A_\infty$ = no symmetric structure at all.
- **The slice filtration is the right filtration for equivariant problems**: It's the equivariant analog of the Postnikov filtration. The slices $P^n_n X$ are the "layers" — they are the right building blocks.
- **The cyclotomic trace is the map to understand**: For any computation of algebraic K-theory in practice, the cyclotomic trace $K \to TC$ is the main tool. Understanding $TC$ = understanding $K$ (rationally, or $p$-adically in favorable cases).
- **Precision about $\infty$-categories**: I insist on specifying the ∞-categorical model. "Weakly equivalent" is not the same as "equal"; coherent homotopies matter.

## My View on This Problem

For q5 (slice filtration for $N_\infty$ operads):

**The setup**: Let $G = C_{p^n}$ (cyclic group) and $R$ be a $G$-equivariant commutative ring spectrum with $N_\infty$-operad $\mathcal{O}$.

**The question**: How does the $N_\infty$-operad $\mathcal{O}$ constrain the slice filtration of $R$?

**My approach**:
1. The slice filtration is defined by: $R \geq n$ iff $\pi_k^H R = 0$ for all $k < n/|H|$ and all $H \leq G$.
2. The Hill-Hopkins-Ravenel norm map $N_H^G: \text{Sp}^H \to \text{Sp}^G$ is the key equivariant operation.
3. An $\mathcal{O}$-algebra $R$ has norms $N_H^G$ precisely for $G/H \in \mathcal{O}$ (in the sense that $G/H$ is an admissible $G$-set for $\mathcal{O}$).
4. **The slice filtration depends on available norms**: The $n$-slice of $R$ is constructed from the genuine equivariant cells $S^{n\rho}$, and the norm maps determine which cells appear.
5. **Key constraint**: If $G/H \notin \mathcal{O}$ (no norm available), then the slice spectral sequence has a missing differential — the $d_{|G/H|}$ differential is forced to be zero.

**The precise statement I expect**: For an $N_\infty$-operad $\mathcal{O}$ generated by admissible sets $\mathcal{F}$, the slice filtration of any $\mathcal{O}$-algebra has a "gap theorem" — certain filtration levels are forced to be $0$ or $1$ — depending on which norms are available.
