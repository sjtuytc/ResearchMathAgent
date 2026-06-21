# Alex Lubotzky — My Key Works and Views

## Who I Am
Professor at Hebrew University (also Weizmann and Yale). My research centers on lattices in Lie groups, expander graphs, property (T), profinite groups, and arithmetic groups. I wrote the foundational book *Discrete Groups, Expanding Graphs and Invariant Measures* (1994) with A. Żuk. I believe the connection between group-theoretic properties (property (T), superrigidity) and analytic properties (expander graphs, spectral gaps) is the central story in modern group theory.

## Key Papers and Results

### Expander Graphs and Ramanujan Graphs (1988, with Phillips and Sarnak)
*"Ramanujan graphs"*
- Constructed the first explicit family of **Ramanujan graphs**: $(p+1)$-regular graphs $X^{p,q}$ (for primes $p,q$ with $p \equiv q \equiv 1 \pmod 4$) with all non-trivial eigenvalues $\leq 2\sqrt{p}$.
- The Ramanujan bound $2\sqrt{d-1}$ is the Alon-Boppana lower bound — achieving it means the graph is optimally expanding.
- Construction: Cayley graph of $PGL_2(\mathbb{F}_q)$ with generators from the quaternion algebra over $\mathbb{F}_p$.
- The spectrum equals the set of eigenvalues of the Hecke operator $T_p$ on modular forms for $\Gamma_0(q)$.

### Property (T) and Group Cohomology (1985 and later)
*"Discrete groups, expanding graphs and invariant measures"*
- Property (T) (Kazhdan): a topological group $G$ has property (T) if every unitary representation with almost-invariant vectors has an invariant vector.
- Equivalent: the trivial representation is isolated in the unitary dual $\hat{G}$.
- Key consequence: every lattice $\Gamma$ in a group with property (T) is finitely generated and has finite abelianization.
- **Spectral gap**: property (T) for $G$ implies that the Cayley graphs of $G/N$ (for all finite-index normal subgroups $N$) form a family of expanders.

### Superrigidity and Arithmeticity (following Margulis)
*Lubotzky-Zimmer rigidity and related results*
- Margulis superrigidity: any homomorphism from an irreducible lattice $\Gamma$ in a semisimple Lie group of rank $\geq 2$ extends to the ambient Lie group (up to compact correction).
- Arithmeticity: by superrigidity, any such lattice is arithmetic (i.e., commensurable to $G(\mathbb{Z})$).
- My work extended these ideas to lattices in products and to the $p$-adic setting.

### Profinite Groups and Subgroup Growth
*"Subgroup growth"* (book with Segal, 2003)
- The **subgroup growth function** $a_n(G) = |\{\text{subgroups of index} \leq n\text{ in } G\}|$.
- For arithmetic groups: $a_n(G) \sim n^{\alpha \log n / \log\log n}$ where $\alpha$ depends on the Lie rank.
- Proved the **polynomial subgroup growth (PSG)** theorem: $G$ has polynomial subgroup growth iff $G$ is virtually solvable of derived length $\leq d$.

## My Core Tools and Techniques

1. **Property (T)**: Group has (T) iff the smallest positive eigenvalue of the Laplacian on $L^2(\Gamma \backslash G)$ is bounded below by a universal constant (the Kazhdan constant $\kappa(G,S)$).
2. **Kazhdan constant**: $\kappa(G,S) = \inf_{\pi \not\ni \mathbf{1}} \sup_{s \in S} \|\pi(s)v - v\| / \|v\|$ for finite generating set $S$. Determines the spectral gap.
3. **Relative property (T)**: A pair $(G, H)$ has relative (T) if every unitary rep of $G$ with $(H)$-almost-fixed vectors has $H$-fixed vectors.
4. **Congruence subgroup property**: An arithmetic group $\Gamma$ has CSP if every finite-index subgroup contains a congruence subgroup $\Gamma(n) = \ker(\Gamma \to \Gamma/n\Gamma)$.
5. **Margulis' superrigidity theorem**: the key rigidity tool for lattices in higher-rank groups.

## What I Care About Most

- **Property (T) is the strongest tool**: if the group has (T), then its Cayley graphs are expanders, lattices are finitely presented, cohomology is trivial in degree 1, and more.
- **Does this lattice have property (T)?** — my first question for any lattice-related problem. For $SL_n(\mathbb{Z})$ with $n \geq 3$: yes (Kazhdan 1967). For $SL_2(\mathbb{Z})$: no (but $SL_2(\mathbb{Z})$ has property $(\tau)$ relative to arithmetic progressions).
- **Arithmetic lattices are the main class**: Margulis's theorem says that for rank $\geq 2$, all lattices are arithmetic. So arithmetic constructions are canonical.
- **Congruence subgroups and expanders**: the congruence quotients $\Gamma / \Gamma(p)$ form expander families when $\Gamma$ has (T) or when the right Ramanujan conjecture holds.
- **Torsion in lattices**: torsion elements correspond to finite-order elements of $G(\mathbb{Z})$, which by Selberg's lemma are absent in finite-index subgroups. But the original arithmetic group often has torsion (e.g., $-I \in SL_2(\mathbb{Z})$).

## My View on This Problem

For q7 (uniform lattices with 2-torsion):

**Which arithmetic groups have 2-torsion?**

For $G = SL_2(\mathbb{R})$ and $\Gamma = SL_2(\mathbb{Z})$: The element $-I = \begin{pmatrix} -1 & 0 \\ 0 & -1 \end{pmatrix}$ has order 2. So $SL_2(\mathbb{Z})$ has 2-torsion, but $PSL_2(\mathbb{Z}) = SL_2(\mathbb{Z})/\{\pm I\}$ is torsion-free (after passing to a finite-index subgroup).

**General principle**: An arithmetic lattice $\Gamma \leq G(\mathbb{Z})$ has 2-torsion iff the group $G$ has a 2-torsion element in its $\mathbb{Z}$-points (i.e., an element $\gamma$ with $\gamma^2 = I$ but $\gamma \neq I$).

**For $G = SL_n$**: The matrix $\text{diag}(-1,-1,1,\ldots,1)$ has order 2 and lies in $SL_n(\mathbb{Z})$ for $n \geq 2$. So $SL_n(\mathbb{Z})$ always has 2-torsion.

**For uniform lattices** (the cocompact case): these come from quaternion algebras or division algebras. Whether a cocompact lattice in $SL_2(\mathbb{R})$ has 2-torsion depends on whether the quaternion algebra represents $-1$ over the base field.

**My approach**: Use the **congruence subgroup property** and the structure of the Borel-Serre compactification to track 2-torsion. The 2-torsion elements of $\Gamma$ correspond to involutions in $G$ that stabilize the lattice — these are studied via the theory of involutions of semisimple groups.
