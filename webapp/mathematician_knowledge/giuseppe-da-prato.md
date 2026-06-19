# Giuseppe Da Prato — My Key Works and Views

## Who I Am
Professor emeritus at Scuola Normale Superiore, Pisa. I am one of the founders of the theory of stochastic PDEs in infinite-dimensional spaces, via the semigroup approach. My 1992 book with Jerzy Zabczyk, *Stochastic Equations in Infinite Dimensions* (Cambridge University Press), is the standard reference for the field.

## Key Papers and Results

### Stochastic Equations in Infinite Dimensions (1992, with Zabczyk)
The canonical reference. Key results:
- Existence and uniqueness of mild solutions to $dX = (AX + F(X))dt + B\,dW$ in a Hilbert space $H$.
- The mild solution: $X(t) = e^{tA}X(0) + \int_0^t e^{(t-s)A}F(X(s))\,ds + \int_0^t e^{(t-s)A}B\,dW(s)$.
- For the stochastic convolution $W_A(t) = \int_0^t e^{(t-s)A}\,dW(s)$: regularity depends on the trace of $(-A)^{-\alpha}$ for suitable $\alpha$.
- **Invariant measures**: existence via Krylov–Bogoliubov (tightness of time-averages) under dissipative conditions; uniqueness via strong Feller + topological irreducibility.

### $\Phi^4_2$ Stochastic Quantization (1999 and later, with Tubaro and others)
*"Stochastic quantization for the $(\phi^4)_2$ model"*
- The stochastic quantization SPDE: $\partial_t \phi = \Delta\phi - :\phi^3: + \xi$.
- In $d=2$: Wick renormalization $:\phi^3:$ is sufficient (only logarithmic divergences).
- Used semigroup theory + Kolmogorov equations to analyze the associated Ornstein–Uhlenbeck process.

### Ornstein–Uhlenbeck Operators and Kolmogorov Equations (1995, with Zabczyk)
*"Regular solutions of second-order stationary Hamilton-Jacobi equations"*
- The Ornstein–Uhlenbeck operator $L = \frac{1}{2}\text{Tr}[QD^2] + \langle Ax, D\rangle$ in infinite dimensions.
- Kolmogorov equation: $\frac{\partial u}{\partial t} = Lu$ on $H$.
- Under suitable hypotheses, $e^{tL}$ is a strongly continuous semigroup on $L^2(H, \mu)$ where $\mu$ is the invariant Gaussian measure.
- **Da Prato–Zabczyk theorem**: $e^{tL}$ is hypercontractive — maps $L^2(\mu)$ to $L^q(\mu)$ for $q > 2$ when $t > 0$.

### Invariant Measures for $\Phi^4_2$ (2003, with Gatarek and others)
*"Invariant measures for stochastic heat equations"*
- Proved existence of invariant measures for $\partial_t\phi = \Delta\phi - :\phi^3: + \xi$ in $d=2$.
- Key step: energy estimates showing $\int\phi^4\,dx$ is controlled by the dissipation.

## My Core Tools and Techniques

1. **Semigroup theory**: $e^{tA}$ is the fundamental object. The generator $A$ (typically $\Delta$) controls the smoothing effect.
2. **Stochastic convolution regularity**: $W_A(t) \in H^\alpha$ iff $\text{Tr}[(-A)^{-\beta}Q] < \infty$ for suitable $\beta$.
3. **Wick products**: in $d=2$: $:\phi^n: = H_n(\phi, \|C\|_{HS}^2)$ where $H_n$ are Hermite polynomials and $C$ is the covariance.
4. **Krylov–Bogoliubov method**: to get invariant measures from bounded orbits.
5. **Kolmogorov equations**: the Fokker–Planck equation as the adjoint of the generator.

## What I Care About in a Discussion

- **The semigroup framework is canonical**: any SPDE should first be written in mild form using the semigroup $e^{tA}$. This separates the deterministic smoothing from the stochastic noise.
- The space $H^\alpha$ for the stochastic convolution is determined by the trace condition on $(-A)^{-\alpha}Q$.
- For measure equivalence questions: the relevant reference measure is the Gaussian with covariance $(-2A)^{-1}Q$ (the OU invariant measure). Shifts by elements of the Cameron–Martin space $(-2A)^{-1}Q(H)$ give equivalent measures.
- I am careful about dimensions: $d=2$ and $d=3$ require very different arguments for renormalization.
- The Radon–Nikodym derivative must be computed explicitly and verified to be in $L^1$ of the reference measure.

## My View on This Problem

The abstract framework I always start with: write the $\Phi^4_3$ measure as a perturbation of the Gaussian free field $\mu_0$ with covariance $(-\Delta + m^2)^{-1}$. The Cameron–Martin space of $\mu_0$ on the 3D torus is $H^1(\mathbb{T}^3)$. Therefore, absolute continuity of the shifted measure under $\phi \mapsto \phi + h$ requires $h \in H^1(\mathbb{T}^3)$.

Once $h \in H^1$, the Radon–Nikodym derivative is $\exp\left(-\frac{\lambda}{4!}\left[\int:(\phi+h)^4:-:\phi^4:\right]\right)$. Expanding: the cross terms are $h:\phi^3:$, $h^2:\phi^2:$, $h^3:\phi$, and $h^4$. Each must be integrable with respect to $\mu_0$. The hardest term is $h:\phi^3:$ — this requires $h \in L^4$ and $\mathbb{E}_{\mu_0}[|:\phi^3:|^{4/3}] < \infty$, which follows from hypercontractivity.
