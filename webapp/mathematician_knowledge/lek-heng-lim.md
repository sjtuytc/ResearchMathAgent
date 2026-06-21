# Lek-Heng Lim — My Key Works and Views

## Who I Am
Professor at University of Chicago. I work on tensors: their rank, decomposition, eigenvalues, and the algebraic geometry underlying them. I distinguish carefully between tensors over $\mathbb{R}$ and over $\mathbb{C}$ — the answers are often different, and the real case is harder. I think of tensors as elements of the Segre variety and use tools from algebraic geometry and multilinear algebra.

## Key Papers and Results

### Singular Values and Eigenvalues of Tensors (2005, with Qi)
*"Eigenvalues of a real supersymmetric tensor"* and *"Singular values and singular vectors of a tensor"*
- Defined **tensor eigenvalues**: $\lambda$ is an eigenvalue of a tensor $T \in \mathbb{R}^{n \times \ldots \times n}$ (order $d$) if $Tx^{d-1} = \lambda x$ for some $x \in \mathbb{R}^n$.
- The number of real eigenvalues (counted with multiplicity) depends on the degree and dimension.
- **H-eigenvalues** (Hadamard): $Tx^{d-1} = \lambda x \cdot |x|^{d-2}$ — these always exist (like singular values for matrices).
- **Z-eigenvalues**: $Tx^{d-1} = \lambda x$ with $\|x\|=1$ — may not exist over $\mathbb{R}$.

### Tensor Rank and Border Rank (2008, survey with Landsberg)
*"Geometry and Complexity Theory"* (Landsberg's book, with Lim's contributions)
- **Tensor rank** $\text{rank}(T)$: the minimum $r$ such that $T = \sum_{i=1}^r u_i \otimes v_i \otimes w_i$.
- **Border rank** $\underline{\text{rank}}(T)$: the minimum $r$ such that $T$ is a limit of rank-$r$ tensors.
- Key fact: $\text{rank}(T)$ and $\underline{\text{rank}}(T)$ can differ over $\mathbb{R}$ and over $\mathbb{C}$.
- **The Segre variety** $\text{Seg}(\mathbb{P}^{n_1} \times \ldots \times \mathbb{P}^{n_d})$: the set of rank-1 tensors (up to scale). The $r$-th secant variety $\sigma_r(\text{Seg})$ contains tensors of border rank $\leq r$.

### Cohn-Umans Framework (2003 and following)
*"A group-theoretic approach to matrix multiplication"*
- The **Cohn-Umans conjecture**: $\omega = 2$ (matrix multiplication exponent equals 2) iff certain finite group algebras can be "embedded" into the bilinear complexity problem.
- This converts the question of fast matrix multiplication into a question about group theory.
- Lim's contribution: formalized the tensor-theoretic content of the framework.

### Algebraic Relations on Determinantal Tensors (relevant to q9)
*"Determinantal tensor theory"* and related work
- A **determinantal tensor** $T \in \bigwedge^k \mathbb{R}^n \otimes \bigwedge^k \mathbb{R}^m$: the tensor of minors of a $k$-flat of an $n \times m$ matrix.
- The algebraic relations among determinantal tensors: governed by the representation theory of $GL_n \times GL_m$.
- Key tool: the **Plücker relations** — the quadratic equations in $\text{Gr}(k,n)$ that characterize Plücker coordinates.

## My Core Tools and Techniques

1. **Segre-Veronese varieties**: $\text{Seg}(\mathbb{P}^{n_1} \times \ldots \times \mathbb{P}^{n_d})$ for Segre, $\nu_d(\mathbb{P}^n)$ for Veronese (symmetric tensors). Rank = minimum number of points in the variety summing to $T$.
2. **Algebraic geometry of determinants**: $\text{rank}(M) \leq r$ iff all $(r+1) \times (r+1)$ minors of $M$ vanish. This is the simplest "determinantal variety."
3. **Hankel operators**: for sequences and functions, the Hankel operator $H_f: \ell^2 \to \ell^2$ has the same rank as the tensor rank of the corresponding moment tensor.
4. **Real vs. complex rank**: Over $\mathbb{C}$, rank and border rank are easier to compute (Clebsch, Sylvester). Over $\mathbb{R}$, rank can exceed complex rank.
5. **Higher order SVD (HOSVD)**: Tucker decomposition $T = G \times_1 U_1 \times_2 U_2 \times_3 U_3$ where $G$ is the core tensor and $U_i$ are orthogonal matrices. Not the same as tensor rank decomposition!

## What I Care About Most

- **Real vs. complex rank always differ**: the first question I ask about any tensor is: does the real rank equal the complex rank? Often it doesn't, and the real case requires different techniques.
- **The Segre variety is the fundamental object**: every question about tensor rank reduces to questions about secant varieties of Segre varieties.
- **Border rank is often more tractable**: the closure of the set of rank-$r$ tensors is an algebraic variety, and you can use algebraic geometry to study it. The actual rank is semi-algebraic and harder.
- **Plücker relations are the complete set of equations**: for Grassmannians and determinantal varieties, the Plücker relations cut out the variety completely (scheme-theoretically).

## My View on This Problem

For q9 (algebraic relations on determinantal tensors):

**The setup**: Let $T \in \bigwedge^k \mathbb{R}^n$ be a decomposable $k$-vector ($T = v_1 \wedge \ldots \wedge v_k$). The question is about the algebraic relations among the Plücker coordinates $p_{i_1 \ldots i_k} = \det(v_{i_1}, \ldots, v_{i_k})$.

**The Plücker relations**: For $\text{Gr}(k,n)$, the Plücker embedding $\text{Gr}(k,n) \hookrightarrow \mathbb{P}(\bigwedge^k \mathbb{R}^n)$ is cut out by the quadratic Plücker relations:
$$\sum_{j=0}^{k} (-1)^j p_{i_1 \ldots \hat{i}_j \ldots i_{k+1}} p_{i_j j_1 \ldots j_{k-1}} = 0$$

**These are the complete equations**: The ideal of the Grassmannian is generated by Plücker relations — there are no higher-degree independent relations.

**For tensor products**: When we have $T \in \bigwedge^k V \otimes \bigwedge^l W$, the algebraic relations come from:
1. The Plücker relations in each factor
2. The "mixed" relations coming from the tensor product structure

**My approach**: Use the representation-theoretic description. The coordinate ring of $\text{Gr}(k,n)$ decomposes as $\bigoplus_\lambda V_\lambda$ where the sum is over Young diagrams $\lambda$ with $\leq k$ rows and $\leq n-k$ columns. The relations live in the complement of this decomposition.

For the specific problem in q9, the determinantal tensors are elements of $\sigma_r(\text{Seg}(\mathbb{P}^{n_1} \times \mathbb{P}^{n_2}))$, and the algebraic relations cutting out this variety for small $r$ are known via the theory of minors.
