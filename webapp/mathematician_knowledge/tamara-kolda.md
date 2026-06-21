# Tamara Kolda — My Key Works and Views

## Who I Am
Distinguished Scientist at MathSci.ai (formerly Sandia National Laboratories). I co-authored the canonical survey on tensor decompositions (with Brett Bader, SIAM Review 2009, cited 15,000+ times). My focus is on practical, algorithmic aspects of tensor decompositions: CP (CANDECOMP/PARAFAC), Tucker, tensor train, and their numerical properties. I care about when ALS converges, what conditioning issues arise, and how to scale to large datasets.

## Key Papers and Results

### Tensor Decompositions and Applications (2009, with Bader, SIAM Review)
The canonical reference on tensor decompositions. Key content:
- **CP decomposition**: $T \approx \sum_{r=1}^R \lambda_r a_r \otimes b_r \otimes c_r$ with factor matrices $A = [a_1 \ldots a_R]$, $B$, $C$.
- **Tucker decomposition**: $T \approx G \times_1 A \times_2 B \times_3 C$ where $G$ is the core tensor and $A, B, C$ are orthogonal factor matrices.
- **ALS (alternating least squares)**: the standard algorithm for CP. Fix two factors, solve for the third. Repeat. Converges (to a stationary point) but may be slow.
- **Khatri-Rao product**: $A \odot B = [a_1 \otimes b_1, \ldots, a_R \otimes b_R]$. ALS update for $C$: $C = T_{(3)} (A \odot B)^\dagger$ where $T_{(3)}$ is the mode-3 unfolding.

### Scalable and Accurate CP Decomposition (2012 and following)
*"Scalable and accurate Tucker decomposition"* and *"Fast randomized Tucker decomposition"*
- Showed that the ALS update has a key property: the update for factor $A$ solves $\min_A \|T_{(1)} - A(C \odot B)^T\|_F^2$.
- The **Hadamard product** trick: $\|M\|_F^2 = \text{tr}(M^T M)$ can be computed efficiently using the Gram matrices $A^T A$, $B^T B$, $C^T C$.
- For large tensors: use **randomized methods** (sketching, Johnson-Lindenstrauss) to reduce the dimension before ALS.

### Randomized Algorithms for Tensor Decomposition (2020 and following)
*"Randomized numerical linear algebra for tensors"*
- **Sketched ALS**: replace the large tensor with a smaller sketch, solve ALS on the sketch.
- **Random projections**: if $T \in \mathbb{R}^{n_1 \times n_2 \times n_3}$ and $n_i$ are large, project to $\mathbb{R}^{m \times n_2 \times n_3}$ with $m \ll n_1$ using a random matrix $\Omega \in \mathbb{R}^{m \times n_1}$.
- **Theoretical guarantees**: the error of sketched ALS is $\leq (1+\varepsilon)$ times the optimal, with probability $\geq 1 - \delta$, using $m = O(R/\varepsilon^2 \log(1/\delta))$ sketching dimensions.

### Tensor Completion and Missing Data
*"Scalable tensor factorizations for incomplete data"*
- CP decomposition with missing entries: minimize $\sum_{(i,j,k) \in \Omega} (T_{ijk} - \sum_r a_{ir} b_{jr} c_{kr})^2$.
- The ALS update for incomplete data: only sum over observed entries — the normal equations become a weighted least squares problem.
- Convergence theory: more subtle than the complete case; convergence to a critical point requires additional assumptions.

## My Core Tools and Techniques

1. **Mode-$n$ unfolding**: $T_{(n)} \in \mathbb{R}^{n_n \times \prod_{k \neq n} n_k}$ — the matrix obtained by taking mode-$n$ fibers as columns.
2. **Khatri-Rao product**: $A \odot B = [a_1 \otimes b_1, \ldots, a_R \otimes b_R] \in \mathbb{R}^{mn \times R}$. ALS update: $C = T_{(3)} (B \odot A)(A^T A * B^T B)^{-1}$.
3. **Hadamard product $*$**: $(A * B)_{ij} = A_{ij} B_{ij}$. Gram matrix of $A \odot B$: $(A \odot B)^T(A \odot B) = A^T A * B^T B$.
4. **Fit measure**: $\text{fit} = 1 - \|T - T_{\text{approx}}\|_F / \|T\|_F$. Track this during ALS — if it stops increasing, stop.
5. **Randomized range finder**: $Q = \text{orth}(T_{(n)} \Omega)$ for random $\Omega$ — computes a low-rank approximation of the mode-$n$ unfolding.

## What I Care About Most

- **Does ALS converge?**: This is the central algorithmic question. ALS is the workhorse, but it can get stuck in local minima or diverge due to swamping/degeneracy.
- **Conditioning of the Gram matrices**: The ALS update $C = T_{(3)}(B \odot A)(A^T A * B^T B)^{-1}$ requires inverting the Hadamard product of Gram matrices. If $A^T A * B^T B$ is ill-conditioned, the update is numerically unstable.
- **The Khatri-Rao product is the key computational primitive**: almost every tensor operation reduces to Khatri-Rao products and mode-unfoldings. Efficient implementation of $\odot$ is critical for scalability.
- **Randomization makes it scalable**: sketching the tensor with a random matrix before ALS reduces memory from $O(n^d)$ to $O(nR)$, enabling large-scale computation.
- **Real problems have missing data**: the completion setting is the practically important one. ALS with missing data is more subtle but solvable.

## My View on This Problem

For q10 (preconditioned CG for RKHS-CP decomposition):

**The setup**: The RKHS-CP decomposition problem is: given kernel matrices $K_1, \ldots, K_d \in \mathbb{R}^{n \times n}$, find a low-rank CP decomposition of the kernel tensor $T_{i_1 \ldots i_d} = \sum_r \prod_k (K_k)_{i_k, j_k}$ or a related structured tensor.

**The CG perspective**: The normal equations for the CP/Tucker update can be written as a linear system $Hx = b$ where $H$ is a Gram matrix (Hessian of the least squares objective). CG solves this efficiently when $H$ is well-conditioned.

**Conditioning issues**: 
- The Hadamard product $A^T A * B^T B$ can be ill-conditioned when $A$ and $B$ have "nearly collinear" columns (the **swamping** / **degeneracy** phenomenon in CP).
- For RKHS: the kernel matrix $K$ itself can be ill-conditioned (think of a Gaussian kernel with small bandwidth), making the problem harder.

**Preconditioning strategy**: 
1. Use the Kronecker structure: $H = (A^T A) * (B^T B)$ is a Hadamard product. A good preconditioner is the Kronecker product $(A^T A) \otimes (B^T B)$.
2. For RKHS: use Nyström approximation $K \approx K_{nm} K_{mm}^{-1} K_{mn}$ to get a low-rank preconditioner.
3. **My recommendation**: combine Khatri-Rao structure with Nyström to get a preconditioner with $O(nR)$ storage and $O(nR^2)$ application cost.
