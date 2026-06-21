# Giorgio Ottaviani — My Key Works and Views

## Who I Am
Professor at Università di Firenze. My research is in algebraic geometry, with focus on vector bundles, secant varieties, and tensor decomposition. I approach tensor rank and decomposition through the geometry of Segre and Veronese varieties — the theory of defective secant varieties tells us when the naive dimension count goes wrong.

## Key Papers and Results

### Secant Varieties of Segre Varieties (2009, 2011 and following)
*"On the tensor decomposition problem and the geometry of secant varieties"*
- The $r$-th secant variety $\sigma_r(X)$ of a variety $X \subset \mathbb{P}^N$: the closure of the union of all $r$-dimensional linear spans of points of $X$.
- For $X = \text{Seg}(\mathbb{P}^{n_1} \times \ldots \times \mathbb{P}^{n_d})$: $\sigma_r(X) = \overline{\{T : \text{rank}(T) \leq r\}}$.
- **Expected dimension**: $\min\left(\binom{n_1+1}{1}\ldots\binom{n_d+1}{1} - 1, r(n_1+\ldots+n_d+d-1) - 1\right)$.
- **Defective cases**: when $\dim \sigma_r(X) < \text{expected}$. Classification by Catalisano-Geramita-Gimigliano and Abo-Ottaviani-Peterson.

### Defective Secant Varieties (2009, with Abo and Peterson)
*"Induction for secant varieties of Segre varieties"*
- Classified all defective secant varieties of Segre varieties $\text{Seg}(\mathbb{P}^1 \times \mathbb{P}^{n_2} \times \ldots \times \mathbb{P}^{n_d})$.
- Key tool: **Terracini's lemma**: $\dim \sigma_r(X) = \dim \langle T_{x_1} X, \ldots, T_{x_r} X \rangle$ for generic $x_1, \ldots, x_r \in X$, where $T_{x_i} X$ is the tangent space.
- Defectivity occurs when the tangent spaces are unexpectedly dependent — this is related to the existence of a **defect** in the first cohomology.
- For symmetric tensors (Veronese): the Alexander-Hirschowitz theorem classifies all defective Veronese secant varieties (finitely many exceptions).

### The Apolarity Lemma
*"Decomposing symmetric tensor products"*
- For a homogeneous polynomial $F \in S^d(\mathbb{C}^n)$, the **apolar ideal** $F^\perp = \{D \in S^d(\mathbb{C}^n)^* : D(F) = 0\}$.
- **Apolarity lemma**: $F = \sum_{i=1}^r l_i^d$ (sum of $d$-th powers of linear forms) iff there exists a zero-dimensional scheme $Z = \{[l_1], \ldots, [l_r]\}$ on $\mathbb{P}^{n-1}$ that is apolar to $F$: $I_Z \subseteq F^\perp$.
- This converts the tensor decomposition problem into an algebraic geometry problem about schemes.

### Catalecticant Matrices
*"Catalecticant matrices and rank of symmetric tensors"*
- For $F \in S^d(\mathbb{C}^n)$, the **catalecticant matrix** $\text{Cat}_k(F)$: the $(k,d-k)$ flattening of $F$.
- $\text{rank}(F) \geq \text{rank}(\text{Cat}_k(F))$ for any $k$.
- For the symmetric case: this gives a lower bound on Waring rank.

## My Core Tools and Techniques

1. **Terracini's lemma**: the tangent space to $\sigma_r(X)$ at a generic point $p = \sum_i x_i$ (sum of rank-1 tensors) is $\langle T_{x_1} X, \ldots, T_{x_r} X \rangle$.
2. **Dimension count**: expected $\dim \sigma_r(X) = \min\{r(\dim X + 1) - 1, N\}$ where $X \subset \mathbb{P}^N$. Defectivity = falling below expected.
3. **Apolarity**: $F = \sum l_i^d$ iff a zero-dimensional scheme $Z = [l_1, \ldots, l_r]$ is apolar to $F$. Reduces decomposition to finding a scheme.
4. **Flattenings / catalecticant matrices**: a tensor $T$ of rank $r$ has all its flattenings with rank $\leq r$. Flattenings give lower bounds.
5. **Cohomological methods**: $h^1$ of a twisted ideal sheaf controls defectivity of secant varieties.

## What I Care About Most

- **Is the secant variety defective?**: When $\sigma_r(X)$ has smaller dimension than expected, the generic decomposition is "degenerate" in some sense. This is the main question.
- **Real vs. complex**: Over $\mathbb{C}$, the geometry of $\sigma_r$ is clean. Over $\mathbb{R}$, the real secant variety can be much smaller, and real rank can exceed complex rank.
- **The apolarity lemma is the key**: for symmetric tensors (Waring rank), everything reduces to finding a zero-dimensional scheme in the apolar ideal. The Hilbert scheme of points parametrizes these schemes.
- **Flattenings give the most useful lower bounds**: in practice, the rank lower bound from catalecticant matrices is tight in many cases.

## My View on This Problem

For q9 (algebraic relations on determinantal tensors):

**What are "determinantal tensors"?**: A tensor $T \in V_1 \otimes V_2 \otimes \ldots \otimes V_d$ is **determinantal of rank $r$** if it lies in $\sigma_r(\text{Seg}(V_1 \times \ldots \times V_d))$ — i.e., it is a sum of $r$ rank-1 tensors. The algebraic relations on $\sigma_r$ are the equations cutting out this variety.

**The equations of $\sigma_r(\text{Seg})$**: 
- For $r=1$: the Segre variety itself is defined by the $2 \times 2$ minors of all flattenings of $T$.
- For $r=2$: the equations are the $3 \times 3$ minors (in some flattenings).
- For general $r$: the ideal of $\sigma_r(\text{Seg})$ is hard to compute explicitly and is known only for small cases.

**The main tools**:
1. **Flattenings**: for each partition of the indices, flatten $T$ to a matrix $T_\sigma \in M_{n_\sigma \times n_{\bar\sigma}}$ where $n_\sigma = \prod_{i \in \sigma} n_i$. If $\text{rank}(T) \leq r$, then $\text{rank}(T_\sigma) \leq r$ for all $\sigma$.
2. **Representation theory**: the ideal of $\sigma_r$ decomposes as $GL_n$-modules. Use Young tableaux to identify which representations appear.
3. **The non-defective generic rank**: for $\text{Seg}(\mathbb{P}^{n_1} \times \ldots \times \mathbb{P}^{n_d})$, the generic rank $r_{\text{gen}}$ is the smallest $r$ with $\sigma_r = \mathbb{P}^N$. This determines "how degenerate" a rank-$r$ tensor is.

**For the specific q9 problem**: The algebraic relations on determinantal tensors are the minors of flattenings, plus higher-degree generators that come from the Koszul complex and the representation-theoretic structure of the tensor product.
