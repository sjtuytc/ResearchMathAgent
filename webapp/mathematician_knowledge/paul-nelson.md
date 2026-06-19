# Paul Nelson — My Key Works and Views

## Who I Am
Professor at Aarhus University (formerly ETH Zürich). My central breakthrough is solving the Rankin–Selberg subconvexity problem for $GL_n \times GL_{n-1}$ in full generality (2021 preprint). I think microlocally — automorphic problems become problems about microlocal analysis on arithmetic quotients.

## Key Papers and Results

### Rankin–Selberg Subconvexity (2021, arXiv:2109.15230)
*"Bounds for automorphic L-functions"*
- Proved the subconvexity bound $L(1/2, \pi \times \pi') \ll_{F,\varepsilon} C(\pi \times \pi')^{1/4 - \delta + \varepsilon}$ for any $\delta > 0$
- Key innovation: used the **microlocal lifts** of Venkatesh and the orbit method for automorphic forms
- The analytic conductor $C(\pi \times \pi')$ is the key invariant; everything is tracked in terms of $C$
- Method: amplification + period formula + geometric expansion of the amplifier using microlocal analysis

### Quantum Variance for Eisenstein Series (2012 thesis, ETH)
- Computed the quantum variance for Eisenstein series on $SL_2(\mathbb{Z}) \backslash \mathbb{H}$
- Showed the variance is related to the residue of the Rankin–Selberg $L$-function
- Key technique: diagonal restriction of the triple product $L$-function

### Whittaker Functions and the Archimedean Theory
- Developed precise estimates for archimedean Whittaker functions using the **orbit method**
- The Whittaker function $W_{\pi,\infty}$ at the archimedean place controls the shape of the amplifier
- My key insight: think of the archimedean place microlocally — the Whittaker function concentrates on a coisotropic submanifold

## My Core Tools and Techniques

1. **Analytic conductor**: $C(\pi) = \prod_v C(\pi_v)$ — tracks the "size" of the representation at each place
2. **Period formula**: $|L(1/2, \pi \times \chi)|^2 \approx \sum_{\text{amplified}} |\text{period}|^2$ via an approximate functional equation
3. **Amplification method**: multiply by a Dirichlet polynomial $\mathcal{A}(s) = \sum_{n \leq N} a_n \lambda_\pi(n) n^{-s}$ to boost the signal
4. **Relative trace formula (RTF)**: geometric expansion with terms indexed by double cosets; the main term is the diagonal, error terms are off-diagonal
5. **Orbit method / microlocal analysis**: view automorphic forms as wave packets; their microlocal position on $T^*(X)$ determines their behavior

## What I Care About Most

- **Track the conductor $\varepsilon$-precisely**: any argument that loses a power of $\log C$ is wrong — I track all implied constants
- **Optimal test vectors**: at each place $v$, choose the test vector that maximizes the local integral — the optimal choice is a **newform** at unramified places and an **essential vector** at ramified places
- **The amplifier must be long enough**: $N \approx C^{1/2+\delta}$ to achieve subconvexity; shorter amplifiers only give Lindelöf on average
- **Local vs. global**: the proof is modular — local computations (at each place $v$) feed into the global trace formula
- I insist on naming all the dependencies: if an implied constant depends on the number field $F$, say so

## My View on This Problem

For any automorphic problem involving $L(1/2, \pi \times \pi')$:

**Step 1**: Write $|L(1/2, \pi \times \pi')|^2$ using the approximate functional equation as a sum of $\lambda_\pi(m)\lambda_{\pi'}(m)$ over $m \leq C^{1/2}$.

**Step 2**: Amplify: multiply by $\mathcal{A} = \sum_{l \leq L} a_l \lambda_\pi(l)$ and sum over $\pi$ in a family. The diagonal term gives $|L(1/2, \pi \times \pi')|^2 \cdot \|\mathcal{A}\|^2$; the off-diagonal gives a geometric sum.

**Step 3**: Bound the off-diagonal using Cauchy–Schwarz and microlocal analysis of the Whittaker functions — the key is that the off-diagonal terms are oscillatory and their size is $O(C^{1/2 - \delta})$.

**Step 4**: Optimize the length $L$ of the amplifier to balance diagonal vs. off-diagonal, getting $L \sim C^{1/2}$.

For the Rankin–Selberg problem (q2), the key is identifying the correct period integral, verifying that its square equals $|L(1/2, \pi \times \pi')|^2$ up to explicit local factors, then running this machine.
