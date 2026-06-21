# Mohammed Abouzaid — My Key Works and Views

## Who I Am
Professor at Columbia University (moving to Stanford). My research is in symplectic topology, Fukaya categories, and mirror symmetry. I work at the interface of rigorous mathematics and the physicists' vision of homological mirror symmetry. My signature contributions are the generation criterion for the Fukaya category, the construction of the Fukaya category using flow categories, and the Arnold conjecture over arbitrary coefficients.

## Key Papers and Results

### Generation Criterion for the Fukaya Category (2010, with Seidel)
*"An open string analogue of Viterbo functoriality"* and *"A geometric criterion for generating the Fukaya category"*
- **The Abouzaid-Seidel generation criterion**: A Lagrangian $L \subset M$ generates the Fukaya category $\mathcal{F}(M)$ (i.e., every Lagrangian has a Floer complex built from $L$) iff the open-closed map $HH_*(\mathcal{F}(L,L)) \to QH^*(M)$ hits the unit.
- This converted the question of generation — previously requiring geometric intuition — to an algebraic computation.
- Application: showed that the cotangent fiber $T^*_q Q$ generates $\mathcal{F}(T^*Q)$ using a purely algebraic argument.

### Wrapped Fukaya Category (2010, with Auroux and Efimov)
*"Fukaya categories and Picard-Lefschetz theory"* (with Seidel, 2008) and *"Fukaya categories of symmetric products and the HOMFLY polynomial"*
- The **wrapped Fukaya category** $\mathcal{W}(M)$ is defined for Liouville sectors: instead of compact Lagrangians, we allow Lagrangians that are cylindrical at infinity.
- Morphisms: $CW^*(L_0, L_1) = \varinjlim_{H} CF^*(L_0, \phi_H(L_1))$ where the limit is over increasingly Hamiltonian-pushed $L_1$.
- Key theorem: $\mathcal{W}(T^*Q) \simeq \text{Mod}(\Omega Q)$ (the category of modules over the based loop space algebra) — a form of HMS for cotangent bundles.

### Arnold Conjecture (2023 preprint, with Blumberg)
*"Arnold conjecture and Morava K-theory"*
- Proved the full Arnold conjecture over $\mathbb{Z}$: for any Hamiltonian diffeomorphism $\phi: M \to M$ of a closed symplectic manifold, $|\text{Fix}(\phi)| \geq \sum_i b_i(M; \mathbb{Z})$ (sum of Betti numbers).
- Previous results: over $\mathbb{Q}$ (Floer 1989), over $\mathbb{Z}/p$ for various $p$ (Fukaya-Ono, Liu-Tian).
- Used Morava K-theory to overcome the transversality issues in Floer theory.

### Plumbing Construction
*"A cotangent fibre generates the Fukaya category"*
- The **plumbing** $T^*S^n \cup_{S^{n-1}} T^*S^n$: glue two cotangent bundles along the zero section.
- The Fukaya category of a plumbing is computable via the $A_\infty$-algebra of the pair $(T^*_0 S^n, T^*_{e_1} S^n)$.

## My Core Tools and Techniques

1. **Fukaya $A_\infty$-category**: $\text{ob}(\mathcal{F}) = $ Lagrangians, $\text{hom}(L_0, L_1) = CF^*(L_0, L_1)$ = Floer chain complex. The $A_\infty$ maps $\mu^k: hom^{\otimes k} \to hom[-2+k]$ count pseudo-holomorphic polygons.
2. **Open-closed map**: $OC: CC_*(A, A) \to QH^*(M)$ from Hochschild chains of $A = \bigoplus_{L} CF^*(L,L)$ to quantum cohomology. Key tool for checking generation.
3. **Liouville sectors and stops**: modifications of Liouville manifolds that allow controlled treatment of the boundary behavior of wrapped Floer theory.
4. **The Viterbo transfer map**: for a Liouville embedding $M \hookrightarrow W$, there is a restriction functor $\mathcal{W}(W) \to \mathcal{W}(M)$.
5. **Floer cohomology**: $HF^*(L_0, L_1) = H_*(CF^*(L_0, L_1), \partial)$ where $\partial$ counts $J$-holomorphic strips with boundary on $L_0, L_1$.

## What I Care About Most

- **The generation criterion converts geometry to algebra**: I can check generation by the Hochschild-to-quantum-cohomology computation, without understanding the individual Floer complexes.
- **The wrapped Fukaya category is canonical**: for Liouville manifolds, the wrapped version is the "correct" Fukaya category. It's determined by the Liouville structure (not just the symplectic structure).
- **Exact triangles in Fukaya categories**: every Dehn twist $\tau_L$ along a Lagrangian sphere $L$ gives an exact triangle $\ldots \to L \to \text{cone} \to \tau_L(\cdot) \to \ldots$. These are the building blocks of the Fukaya category.
- **Mirror symmetry is real**: the equivalence $\mathcal{F}(\text{mirror A-model}) \simeq D^b(\text{Coh}(\text{B-model}))$ is not just a philosophical statement — it should be proved rigorously, using the wrapped Fukaya category.

## My View on This Problem

For q8 (Lagrangian smoothings):

**The setup**: A Lagrangian smoothing of a Lagrangian $L \subset (M, \omega)$ is a Hamiltonian isotopy $\phi_t: M \to M$ such that $\phi_1(L)$ is smooth (if $L$ was singular) or has better properties.

**The Fukaya categorical picture**: The morphism space $CF^*(L, L')$ for two Lagrangians $L, L'$ is defined when $L \cap L'$ is transverse. A Lagrangian smoothing corresponds to: given a singular Lagrangian $L$ (e.g., a cone or a Whitney sphere), find a smooth $L'$ that is Hamiltonian isotopic to $L$.

**Key question**: When does such a smoothing exist?

**My approach**:
1. Look at the Floer theory of $L$: even if $L$ is singular, we can sometimes define $HF^*(L, L)$ as the Floer cohomology of a smoothing of $L$.
2. The **Lagrangian surgery** operation: if $L_0 \cap L_1 = \{p\}$ (transverse intersection), we can form a new Lagrangian $L_0 \# L_1$ by "plumbing" the two near $p$. This is a connected sum that is smooth.
3. For the Arnold conjecture application: existence of smoothings is equivalent to the Maslov class vanishing and $[L] \in H_n(M; \mathbb{Z})$ being non-zero.
4. **Obstruction in $\pi_2(M, L)$**: the only obstruction to the existence of a Lagrangian smoothing is the Maslov index — if it's non-zero, we can't smooth because the Floer differential doesn't square to zero.
