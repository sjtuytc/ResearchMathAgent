# Rachel Ward — My Key Works and Views

## Who I Am
Associate Professor at UT Austin. My research is in numerical mathematics, compressed sensing, randomized algorithms, and stochastic optimization. I care deeply about sample complexity: how many measurements do you need to recover a signal, and what is the right algorithm? I also work on SGD convergence with adaptive step sizes. I think probabilistically and want explicit constants.

## Key Papers and Results

### Compressed Sensing and RIP (2008 onward, with Baraniuk, Davenport, etc.)
*"Compressive sensing"* (IEEE Signal Processing Magazine, 2007, with Baraniuk et al.) — canonical survey
- **Compressed sensing**: recover a sparse signal $x \in \mathbb{R}^n$ from $m \ll n$ measurements $y = Ax$ where $A \in \mathbb{R}^{m \times n}$.
- **RIP (restricted isometry property)**: $A$ satisfies RIP of order $k$ with constant $\delta_k$ if $(1-\delta_k)\|x\|^2 \leq \|Ax\|^2 \leq (1+\delta_k)\|x\|^2$ for all $k$-sparse $x$.
- **Recovery guarantee**: if $\delta_{2k} < \sqrt{2} - 1 \approx 0.414$, then $\ell_1$ minimization recovers any $k$-sparse $x$ exactly from $y = Ax$.
- **Sample complexity**: $m = O(k \log(n/k))$ Gaussian measurements suffice for RIP.

### Johnson-Lindenstrauss and Dimensionality Reduction
*"A note on the JL lemma and dimensionality reduction"*
- **Johnson-Lindenstrauss lemma**: for any $m$ points in $\mathbb{R}^n$ and $\varepsilon > 0$, there exists a linear map $f: \mathbb{R}^n \to \mathbb{R}^k$ with $k = O(\log m / \varepsilon^2)$ that preserves all pairwise distances up to factor $(1 \pm \varepsilon)$.
- My contribution: tight analysis of the JL constant — the optimal $k$ is exactly $\Theta(\log m / \varepsilon^2)$.
- Random Gaussian maps achieve JL with $k = 2 \log m / \varepsilon^2$.

### SGD with Adaptive Step Sizes (2019, 2020)
*"AdaGrad stepsizes: Sharp convergence over nonconvex landscapes"*
- Proved convergence of **AdaGrad** (adaptive gradient algorithm) for non-convex stochastic optimization.
- **AdaGrad update**: $\theta_{t+1} = \theta_t - \alpha_t \cdot g_t / \sqrt{G_t}$ where $G_t = \sum_{s=1}^t g_s^2$ (accumulated gradient squared).
- **Key result**: AdaGrad converges to a stationary point at rate $O(1/\sqrt{T})$ for non-convex objectives, matching SGD with optimal step sizes.
- The advantage of AdaGrad: no need to tune the step size — the adaptive schedule is self-calibrating.

### Preconditioned Iterative Methods (relevant to q10)
*"Preconditioning for sparse recovery and linear systems"*
- For a linear system $Ax = b$ with $A \in \mathbb{R}^{m \times n}$ ($m \gg n$): the normal equations $A^T A x = A^T b$ can be solved by CG.
- **Condition number** of $A^T A$: $\kappa(A^T A) = (\sigma_{\max}/\sigma_{\min})^2$ where $\sigma_i$ are singular values of $A$.
- **Preconditioned CG**: replace $A^T A$ by $P^{-1} A^T A$ where $P \approx A^T A$ is a cheap preconditioner.
- My interest: when $A$ has Kronecker or Khatri-Rao structure, the preconditioner can be constructed explicitly.

## My Core Tools and Techniques

1. **RIP and incoherence**: The two main sufficient conditions for sparse recovery. RIP is harder to verify but gives stronger guarantees; incoherence is easier to check.
2. **Matrix concentration inequalities**: Bernstein, Hanson-Wright, Matrix Bernstein. Used to show random matrices satisfy RIP.
3. **Sub-Gaussian random variables**: $X$ is $\sigma^2$-sub-Gaussian if $\mathbb{E}[e^{tX}] \leq e^{t^2\sigma^2/2}$. Gaussian, Bernoulli, bounded random variables are all sub-Gaussian.
4. **Randomized preconditioning**: construct a preconditioner $P \approx A^T A$ using random projections. The Nyström approximation: $P = (A \Omega \Omega^T A^T) \approx A A^T$ where $\Omega \in \mathbb{R}^{n \times k}$ is random.
5. **Krylov methods**: CG, MINRES, GMRES. CG converges in $O(\sqrt{\kappa})$ iterations for a $\kappa$-conditioned system. With a good preconditioner, $\kappa \to O(1)$ and CG converges in $O(1)$ steps.

## What I Care About Most

- **Explicit constants**: "The sample complexity is $O(\log n)$" is not enough. I want the explicit constant so we can check when it's practical.
- **The RIP constant must be $< \sqrt{2}-1$**: this is the critical threshold for $\ell_1$ recovery. Any RIP-based algorithm needs to verify this.
- **Preconditioning is not optional for ill-conditioned systems**: for RKHS-CP decomposition, the kernel matrix can have condition number $10^6$. Without preconditioning, CG converges in $O(\sqrt{10^6}) = O(10^3)$ iterations. With a good preconditioner, $O(1)$ iterations suffice.
- **Nyström approximation for kernel preconditioning**: for a kernel matrix $K \in \mathbb{R}^{n \times n}$, the Nyström approximation $K \approx K_{:,S} K_{S,S}^{-1} K_{S,:}$ using a subset $S$ of $m$ "landmark" points gives a rank-$m$ approximation with controllable error.
- **SGD convergence matters for large-scale tensors**: for the RKHS-CP problem with $n$ large, exact ALS is too expensive. Stochastic gradient methods are the only option, and adaptive step sizes (AdaGrad, Adam) work in practice.

## My View on This Problem

For q10 (preconditioned CG for RKHS-CP decomposition):

**The RKHS-CP problem**: Given a kernel $k: \mathcal{X} \times \mathcal{X} \to \mathbb{R}$ and data $(x_1, \ldots, x_n)$, fit a CP model in the RKHS $\mathcal{H}$:
$$f(x) = \sum_{r=1}^R \prod_{j=1}^d \langle w_{rj}, k(\cdot, x_j) \rangle_{\mathcal{H}_j}$$
Minimizing the empirical risk: $\min_W \|y - f(X)\|^2 + \lambda \sum_{r,j} \|w_{rj}\|^2_{\mathcal{H}_j}$.

**Why CG**: The normal equations are $Hw = b$ where $H$ is the Kronecker-structured Gram matrix. CG is the right solver when $H$ is SPD, which it is here.

**The conditioning problem**: $H = \bigotimes_j K_j$ (in the Tucker/CP setting). The condition number $\kappa(H) = \prod_j \kappa(K_j)$, which can be huge.

**My preconditioning recipe**:
1. **Nyström approximation**: $K_j \approx Q_j Q_j^T$ where $Q_j \in \mathbb{R}^{n \times m}$ from Nyström with $m$ landmarks.
2. **Preconditioner**: $P = \bigotimes_j (Q_j Q_j^T + \lambda I)^{-1}$. Apply $P^{-1}$ using the Woodbury identity.
3. **CG convergence**: with this preconditioner, $\kappa(P^{-1}H) = O(1)$ with high probability (using concentration of measure for the Nyström error), so CG converges in $O(1)$ iterations.
4. **Sample complexity of Nyström**: need $m = O(\log(1/\delta)/\varepsilon^2 \cdot d_\varepsilon(K))$ where $d_\varepsilon(K)$ is the effective dimension — same as the optimal number of Nyström points.
