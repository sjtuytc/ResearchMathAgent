<!-- Generated 2026-05-24T19:18:29 -->
<!-- Source: https://arxiv.org/pdf/0808.0163 -->

# Batson, Spielman, Srivastava — "Twice-Ramanujan Sparsifiers" (arxiv:0808.0163)

## Definitions
- **Definition 3.2.** For u,l ∈ R and A a symmetric matrix with eigenvalues λ1,λ 2,...,λ n, deﬁne: Φu(A) def = Tr(uI−A)−1 = ∑i 1 / (u−λi) (Upper potential). Φl(A) def = Tr(A−lI)−1 = ∑i 1 / (λi−l) (Lower potential).

## Lemmas, Theorems, Propositions, Corollaries
- **Theorem 1.1.** For every d> 1, every undirected weighted graph G = (V,E,w ) on n vertices contains a weighted subgraph H = (V,F, ˜w) with ⌈d(n− 1)⌉ edges (i.e., average degree at most 2d) that satisﬁes: xTLGx≤xTLHx≤ ( d + 1 + 2√d / d + 1− 2√d ) ·xTLGx ∀x∈ RV.
  *Proof:* Reduces the graph approximation problem to matrix approximation by applying Theorem 3.1 to the columns of the incidence matrix, concluding with the Courant-Fischer Theorem.
- **Lemma 2.1 (Sherman-Morrison Formula).** If A is a nonsingular n×n matrix and v is a vector, then (A + vvT )−1 =A−1− A−1vvTA−1 / (1 + vTA−1v).
  *Proof:* (no proof in this paper)
- **Lemma 2.2 (Matrix Determinant Lemma).** If A is nonsingular and v is a vector, then det(A + vvT ) = det(A)(1 + vTA−1v).
  *Proof:* (no proof in this paper)
- **Theorem 3.1.** Suppose d> 1 and v1, v2,..., vm are vectors in Rn with ∑i≤m vivTi = idRn. Then there exist scalars si≥ 0 with |{i :si̸= 0}|≤ dn so that idRn⪯ ∑i≤m sivivTi ⪯ ( d + 1 + 2√d / d + 1− 2√d ) idRn.
  *Proof:* Constructs the sparse matrix iteratively by adding one rank-one update at a time while tracking eigenvalues via upper and lower barrier potential functions. Uses the Sherman-Morrison formula to bound the potential shifts and an averaging argument to guarantee a valid update exists at every step.
- **Lemma 3.3 (Upper Barrier Shift).** Suppose λmax(A)<u , and v is any vector. If 1/t ≥ vT ((u +δU)I−A)−2v / (Φu(A)− Φu+δU (A)) + vT ((u +δU)I−A)−1v def = UA(v) then Φu+δU (A +tvvT )≤ Φu(A) and λmax(A +tvvT )<u +δU.
  *Proof:* Computes the trace of the updated inverse using the Sherman-Morrison formula and algebraically isolates the condition on the step size.
- **Lemma 3.4 (Lower Barrier Shift).** Suppose λmin(A)>l , Φl(A)≤ 1/δL, and v is any vector. If 0< 1/t ≤ vT (A− (l +δL)I)−2v / (Φl+δL(A)− Φl(A)) − vT (A− (l +δL)I)−1v def = LA(v) then Φl+δL(A +tvvT )≤ Φl(A) and λmin(A +tvvT )>l +δL.
  *Proof:* Applies the Sherman-Morrison formula to the lower barrier inverse and rearranges the resulting trace expression to bound the allowable update weight.
- **Lemma 3.5 (Both Barriers).** If λmax(A) < u, λmin(A) > l, Φu(A)≤ ϵU, Φl(A)≤ ϵL, and ϵU,ϵL,δU and δL satisfy 0≤ 1/δU +ϵU≤ 1/δL −ϵL (3) then there exists an i and positive t for which LA(vi)≥ 1/t≥UA(vi), λ max(A +tvivTi )<u +δU, and λmin(A +tvivTi )>l +δL.
  *Proof:* Uses an averaging argument over all vectors to express the sums of potential bounds as matrix traces. Invokes Claim 3.6 to show the lower bound limit exceeds the upper bound limit, guaranteeing a valid update vector exists.
- **Lemma 4.1.** Let LH = (V,E,w ) be a graph that (1 +ϵ)-approximates LG, the complete graph on V . Then, for every pair of disjoint sets S and T , |w(S,T )− ( 1 + ϵ / 2 ) |S||T| |≤n(ϵ/2) √|S||T|, where w(S,T ) denotes the sum of the weights of edges between S and T .
  *Proof:* Expresses the sparsifier's Laplacian as a perturbation of the complete graph's Laplacian and evaluates the quadratic form on the characteristic vectors of the disjoint sets.
- **Proposition 4.2.** Let G be the complete graph on vertex set V , and let H = (V,E,w ) be a weighted graph with n vertices and a vertex of degree d. If H κ-approximates G, then κ≥ 1 + 2√d −O ( √d / n ) .
  *Proof:* Constructs test vectors assigning specific weights to the degree-d vertex and its neighbors to evaluate the Laplacian quadratic forms. Projects these vectors orthogonal to the all-ones vector and computes the asymptotic ratio of the forms to establish the lower bound.