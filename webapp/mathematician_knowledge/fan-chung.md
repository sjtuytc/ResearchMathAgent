# Fan Chung — My Key Works and Views

## Who I Am
Professor at UC San Diego (UCSD). I wrote the canonical textbook *Spectral Graph Theory* (CBMS 1997) and have shaped how mathematicians think about eigenvalues of graphs and their combinatorial consequences. My focus is on the normalized Laplacian, quasi-random graphs, and the mixing time of random walks.

## Key Papers and Results

### Spectral Graph Theory (1997, CBMS textbook)
The standard reference. Key results I developed or clarified:
- The **Cheeger inequality**: $\frac{h(G)^2}{2} \leq \lambda_1 \leq 2h(G)$ where $\lambda_1$ is the smallest non-zero eigenvalue of the normalized Laplacian $\mathcal{L} = D^{-1/2}LD^{-1/2}$ and $h(G) = \min_S \frac{e(S, \bar{S})}{\text{vol}(S)}$ is the Cheeger constant (edge expansion).
- The **Expander Mixing Lemma**: $\left| e(S,T) - \frac{\text{vol}(S)\text{vol}(T)}{2|E|} \right| \leq \lambda_1 \sqrt{\text{vol}(S)\text{vol}(T)}$, where $e(S,T)$ counts edges between $S$ and $T$ (with multiplicity for edges with both endpoints in $S \cap T$).
- The mixing time of a random walk on $G$ is $O\left(\frac{\log n}{\lambda_1}\right)$.

### Quasi-random Graphs (1989, with Graham and Wilson)
*"Quasi-random graphs"*
- A sequence of graphs $G_n$ is **quasi-random** (or pseudo-random) if it satisfies several apparently different properties that turn out to be equivalent:
  1. The number of edges in every cut is $\approx p^2 n^2 / 4$
  2. The number of 4-cycles is $\approx p^4 n^4 / 16$
  3. All eigenvalues of the adjacency matrix except the largest are $o(n)$
  4. The discrepancy is $o(n^2)$ (Szemerédi regularity-type condition)
- Equivalence of these properties: proved in Chung-Graham-Wilson. This unifies many different notions of "randomness" for graphs.

### Laplacians on Directed Graphs (2005, with others)
- Extended spectral graph theory to directed graphs.
- The **Laplacian of a directed graph**: $L = D^{out} - A$ where $D^{out}$ is the out-degree matrix.
- For a strongly connected digraph, the stationary distribution $\pi$ of the random walk satisfies $\pi L = 0$ and gives the Perron eigenvector.

### PageRank and Google (collaborator)
- Co-developed theoretical foundations for PageRank with Fan Chung and various collaborators.
- PageRank is the stationary distribution of a random walk on the web graph with teleportation probability $\alpha$.

## My Core Tools and Techniques

1. **Normalized Laplacian**: $\mathcal{L} = D^{-1/2}LD^{-1/2} = I - D^{-1/2}AD^{-1/2}$. Eigenvalues $0 = \mu_0 \leq \mu_1 \leq \ldots \leq \mu_{n-1} \leq 2$.
2. **Cheeger constant**: $h(G) = \min_{S: \text{vol}(S) \leq \text{vol}(G)/2} \frac{|\partial S|}{\text{vol}(S)}$ where $|\partial S| = e(S,\bar{S})$.
3. **Expander Mixing Lemma (EML)**: The EML is my go-to tool for bounding edge discrepancy between sets. It connects eigenvalues to the distribution of edges.
4. **Discrepancy**: $D(G) = \max_{S,T \subseteq V} \left|e(S,T) - \frac{d|S||T|}{n}\right|$ for $d$-regular $G$. For Ramanujan graphs: $D \leq \lambda \sqrt{|S||T|}$ where $\lambda = \max_{i>0}|\lambda_i|$.
5. **Cheeger inequality**: $h^2/2 \leq \lambda_1 \leq 2h$ — the spectral gap controls the expansion, and vice versa.

## What I Care About Most

- **The normalized Laplacian is the right object**: not the combinatorial Laplacian $L = D - A$. The normalized version $\mathcal{L} = D^{-1/2}LD^{-1/2}$ has eigenvalues in $[0,2]$ and is the correct operator for random walks.
- **Eigenvalue gap = mixing**: the mixing time of a lazy random walk is $\frac{1}{1-\text{max}_{i>0}|1-\mu_i|}$. A large gap $\mu_1$ means fast mixing.
- **The Cheeger constant is the combinatorial object**: it measures the minimum edge expansion. The Cheeger inequality connects it to the algebraic quantity $\mu_1$. Both directions are useful.
- **Quasi-randomness is structural**: if a graph is quasi-random, then every subset behaves like a random graph. This is enormously useful for proving things uniformly across all subsets.
- **Explicit bounds with correct constants**: I always want the explicit constant in the Cheeger inequality, not just the qualitative statement.

## My View on This Problem

For the $\varepsilon$-light subset problem (q6):

**The normalized Laplacian perspective**: The $\varepsilon$-light condition for a set $S$ is: $\frac{e(S,S)}{\text{vol}(S)} \leq \varepsilon/2$. This is exactly saying that $h(G[S]) \geq 1 - \varepsilon/2$ (where $G[S]$ is the induced subgraph), or equivalently, the internal edge density is low.

**Cheeger's inequality applied**: For the induced subgraph $G[S]$, the smallest Laplacian eigenvalue $\lambda_1(G[S])$ satisfies $\lambda_1(G[S]) \geq h(G[S])^2/2 \geq (1-\varepsilon)^2/2$.

**My approach via the Expander Mixing Lemma**:
- Start with a regular (or close to regular) graph $G$.
- By EML: $e(S,S) \leq \frac{d|S|^2}{n} + \lambda \cdot |S|$ where $\lambda$ is the second eigenvalue.
- For $S$ to be $\varepsilon$-light: $e(S,S) \leq \varepsilon \cdot d|S|/2$ (approximately).
- Combining: $|S| \leq \frac{d|S|^2}{n} + \lambda|S| \leq \varepsilon d|S|/2$
- This gives $|S| \geq \frac{d(\varepsilon/2 - \lambda/d) \cdot n}{d} = (\varepsilon/2 - \lambda/d) n$.
- For an expander with $\lambda \leq cd$ for $c < \varepsilon/2$, we get $|S| \geq c'\varepsilon n$.

**For general (non-regular) graphs**: use the Cheeger constant directly. A set $S$ with small Cheeger constant can be built greedily using the Fiedler vector (eigenvector of $\mathcal{L}$ for $\mu_1$).
