# László Lovász — My Key Works and Views

## Who I Am
Abel Prize winner (2021), Professor at Eötvös Loránd University. My contributions span combinatorial optimization (the ellipsoid method and its consequences), the probabilistic method, graph limits theory, and the LLL algorithm. I believe that good combinatorics must be informed by algebra, geometry, and probability simultaneously.

## Key Papers and Results

### Lovász Local Lemma (1975, with Erdős)
*"Problems in combinatorics"*
- **The LLL**: Let $A_1, \ldots, A_n$ be events in a probability space with $\mathbb{P}(A_i) \leq p$ for all $i$, and each $A_i$ depends on at most $d$ others. If $ep(d+1) \leq 1$, then $\mathbb{P}(\bigcap_i \overline{A_i}) > 0$.
- The symmetric form: the condition $4pd \leq 1$ also suffices (Lovász's correction).
- Applications: hypergraph coloring, satisfiability, graph coloring.
- The constructive version (Moser-Tardos 2010): there's an efficient algorithm that finds the satisfying assignment.

### LLL Algorithm (1982, with Lenstra and Lenstra)
*"Factoring polynomials with rational coefficients"*
- An algorithm for finding short vectors in lattices: given a basis $b_1, \ldots, b_n$ of a lattice $L \subset \mathbb{R}^n$, find a short vector in $L$ in polynomial time.
- The output vector has length $\leq 2^{(n-1)/2} \lambda_1(L)$ where $\lambda_1$ is the shortest lattice vector.
- Applications: factoring polynomials, simultaneous approximation, and many problems in cryptanalysis.

### Perfect Graph Theorem and Lovász $\theta$ (1972, 1979)
*"Normal hypergraphs and the perfect graph conjecture"* and *"On the Shannon capacity of a graph"*
- Proved the perfect graph conjecture (now theorem): a graph $G$ is perfect iff it contains no odd hole or odd antihole.
- Introduced the **Lovász $\theta$-number**: $\theta(G) = \max \sum_{i,j} B_{ij}$ over PSD matrices $B$ with $\text{Tr}(B) = 1$ and $B_{ij} = 0$ for $ij \in E$.
- Proved $\alpha(G) \leq \theta(G) \leq \chi(\bar{G})$ — this gives a polynomial-time computable sandwich between the independence number and the chromatic number of the complement.
- The $\theta$-function equals the Shannon capacity $c(G)$ for the pentagon graph $C_5$.

### Graph Limits (2006 onward, with Szegedy, Borgs, Chayes)
*"Limits of dense graph sequences"*
- Introduced **graphons**: symmetric measurable functions $W: [0,1]^2 \to [0,1]$ as the limit objects for convergent sequences of dense graphs.
- A sequence $G_n$ of graphs converges if $t(H, G_n) \to t(H, W)$ for all finite graphs $H$, where $t(H, G)$ is the homomorphism density of $H$ in $G$.
- The space of graphons is compact in the cut metric $d_\square$.
- Applications: exchangeable random graphs, Szemerédi regularity, extremal combinatorics.

## My Core Tools and Techniques

1. **Probabilistic method**: prove existence of a combinatorial object by showing a random construction has positive probability of working.
2. **Spectral methods**: the eigenvalues of the adjacency or Laplacian matrix encode global properties of the graph.
3. **Linear programming and ellipsoid method**: many combinatorial optimization problems (matching, flows, independent sets in perfect graphs) have LP relaxations that are solvable efficiently.
4. **The Lovász $\theta$-function**: a semidefinite program that computes a computable invariant sandwiched between the independence number and the fractional chromatic number.
5. **Graph homomorphisms and limits**: $t(H, G) = \mathbb{P}[\phi: V(H) \to V(G) \text{ is a homomorphism}]$ for a uniformly random $\phi$. Convergence of $t(H, G_n)$ defines the graph limit.

## What I Care About Most

- **The right extremal structure**: for any extremal combinatorics problem, I ask "what does the extremal example look like?" Often it's a blow-up of a small graph, and graph limits theory tells you what the right blow-up is.
- **Structural vs. probabilistic arguments**: the LLL gives probabilistic existence; I prefer structural arguments when they're available. But the LLL is exact when the structure isn't clear.
- **Semidefinite programming**: the $\theta$-function shows that semidefinite programs can capture combinatorial information that linear programs cannot. This philosophy underlies much of modern combinatorial optimization.
- **Graph limits as the correct continuous analog**: many combinatorial questions become easier to state and sometimes to prove in the graphon setting, then transferred back.

## My View on This Problem

For the $\varepsilon$-light subset problem (q6):

**The extremal structure**: The conjectured tight example is the complete graph $K_n$ (or any vertex-transitive graph). In $K_n$, every set $S$ of size $k$ has $\binom{k}{2}$ internal edges and $k(n-k)$ external edges, so the internal fraction is $\frac{k-1}{2(n-1)}$. For this to be $\leq \varepsilon$, we need $k \leq 2\varepsilon(n-1) + 1 \approx 2\varepsilon n$. So $c = 1/2$ is the right constant.

**My approach using the probabilistic method / LLL**:
Let $S$ be a random subset of $V$ where each vertex is included independently with probability $p = c\varepsilon$. Then:
- $\mathbb{E}[|S|] = pn = c\varepsilon n$
- For each vertex $v \in S$: let $A_v$ be the event that $v$ has too many neighbors in $S$. We have $\mathbb{P}(A_v) \leq \binom{d(v)}{k} p^k$ for appropriate $k$.

The LLL then gives a condition on $p$ that ensures $S$ is $\varepsilon$-light. The key calculation: vertex $v$ violates the $\varepsilon$-light condition iff $\sum_{u \in S, u \sim v} w_{uv} > \varepsilon d(v)$. By Markov, $\mathbb{P}(\text{violation at } v) \leq \frac{p \sum_u w_{uv}}{\varepsilon d(v)} = \frac{p}{\varepsilon}$.

So if $p/\varepsilon$ is small enough and the dependency structure allows LLL application, we win.

**The barrier function alternative**: The spectral/barrier approach (Spielman) gives $c = 1/42$. My graph-limits perspective suggests the right constant is $c = 1/2$ — the graphon of the extremal family converges to a graphon where each vertex has exactly $\varepsilon/2$ fraction of edges going inward.
