"""Rich hierarchical document system for ResearchMathAgent.

Directory layout under documents/:
  questions/
    q{N}/
      overview.md    — static: problem, background, key theorems, why it's hard
      timeline.md    — append-only: every attempt in chronological order
      progress.md    — live: current status, best result, open gaps, next steps
      strategies.md  — live: strategy space, what's tried/untried, agent insights
  discussions/
    index.md         — cross-problem insights, thematic clusters, proof patterns
    cluster_*.md     — per-cluster deep dives
  strategy_memory.jsonl  — raw JSONL log (append-only, feeds all docs)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Problem knowledge base ────────────────────────────────────────────────────

PROFILES: dict[str, dict] = {
    "q1": {
        "title": r"Problem 1: $\Phi^4_3$ Measure Quasi-Invariance",
        "area": "Stochastic Analysis / Euclidean Quantum Field Theory",
        "author": "Martin Hairer (EPFL / Imperial College London)",
        "candidate": "**Yes.** The $\\Phi^4_3$ Gibbs measure is quasi-invariant under smooth Cameron-Martin shifts.",
        "strategy": (
            "Apply the Cameron-Martin theorem to the Gaussian reference measure on $\\mathcal{D}'(\\mathbb{T}^3)$. "
            "The smooth shift $T_\\psi(u)=u+\\psi$ with $\\psi\\in H^1$ lies in the Cameron-Martin space of the GFF. "
            "Expand the Wick-renormalized interaction $:u^4:$ before and after the shift; the difference is a finite "
            "linear combination of Wick powers $:u^k:$ with smooth coefficients. Exponential integrability of this "
            "density difference (w.r.t. the Gaussian measure) follows from Nelson's hypercontractivity."
        ),
        "key_theorems": [
            "Cameron-Martin theorem (quasi-invariance of Gaussian measures under H-shifts)",
            "Nelson hypercontractivity (exponential integrability of Wick polynomials)",
            "Da Prato–Zabczyk theory (SPDEs in infinite dimensions)",
            "Hairer regularity structures (construction of $\\Phi^4_3$)",
        ],
        "definitions": [
            "$\\Phi^4_3$ measure: the Gibbs measure $d\\mu = Z^{-1}\\exp(-\\int :u^4:)\\,d\\mu_{GFF}$ on $\\mathcal{D}'(\\mathbb{T}^3)$",
            "Cameron-Martin space of GFF on $\\mathbb{T}^3$: the Sobolev space $H^1(\\mathbb{T}^3)$",
            "Wick renormalization $:u^k:$: the $k$-th Hermite polynomial in $u$ w.r.t. the Gaussian reference",
            "Quasi-invariance: measures $\\mu$ and $T_\\psi^*\\mu$ are mutually absolutely continuous",
        ],
        "connections": ["q4 (heat flow + measure theory analogy)", "q8 (infinite-dimensional geometry)"],
        "difficulty": (
            "The $\\Phi^4_3$ field $u$ lives in $H^{-1/2-\\varepsilon}$, strictly below the Cameron-Martin space $H^1$. "
            "So the shift $T_\\psi$ does not act on the support of $\\mu$ in a naive sense — the Cameron-Martin formula "
            "holds only for the *Gaussian* part. The hard step is showing that the Wick-renormalized interaction "
            "density $\\exp(\\Delta H)$ — the Radon-Nikodym derivative from the interaction — is integrable with "
            "respect to the shifted Gaussian. This requires precise hypercontractivity estimates on Wiener chaos."
        ),
        "boundary_cases": [
            "$\\psi = 0$: trivially quasi-invariant (identity map)",
            "Singular $\\psi \\notin H^1$: the Cameron-Martin formula fails; this is the hard boundary",
        ],
        "research_context": (
            "Hairer's 2014 Fields Medal was awarded partly for constructing the $\\Phi^4_3$ measure via regularity structures. "
            "Quasi-invariance is related to the ergodicity of the stochastic quantization dynamics $\\partial_t u = -Lu + :u^3: + \\xi$. "
            "Connections to the renormalization group (what happens as the cutoff is removed) are an active research area."
        ),
    },
    "q2": {
        "title": r"Problem 2: Nonvanishing of Local Rankin-Selberg Integrals",
        "area": "Local Representation Theory / Automorphic Forms",
        "author": "Paul Nelson (University of Arizona)",
        "candidate": "**Yes.** There exist test vectors $W\\in\\Pi$, $V\\in\\pi$ such that the local Rankin-Selberg integral $\\Psi(s,W,V)$ is nonzero.",
        "strategy": (
            "Work in the Kirillov/Whittaker model for $\\pi$ and $\\Pi$. The conductor translate $u_Q = \\operatorname{diag}(\\varpi^{-Q},\\ldots)$ "
            "aligns the ramification of $\\pi$ with the support of a compactly supported matrix coefficient. "
            "Construct $W\\in\\Pi$ with compact support near $\\operatorname{diag}(g,1)u_Q$ in $N_{n+1}\\backslash GL_{n+1}$; "
            "choose $V$ in the Whittaker model of $\\pi$ with support where the integrand is nonzero. "
            "The local integral then factors as a product of local zeta integrals that do not all vanish simultaneously."
        ),
        "key_theorems": [
            "Local Langlands correspondence for $GL_n$ (Zelevinsky classification of representations)",
            "Bernstein–Zelevinsky theory (Kirillov and Whittaker models for p-adic $GL_n$)",
            "Nondegeneracy of Rankin-Selberg pairing (local functional equation)",
            "Casselman-Shalika formula (values of spherical Whittaker functions)",
        ],
        "definitions": [
            "$\\Pi$: an irreducible admissible representation of $GL_{n+1}(F)$ (F a non-archimedean local field)",
            "$\\pi$: an irreducible admissible representation of $GL_n(F)$",
            "Whittaker model $\\mathcal{W}(\\pi, \\psi)$: the unique embedding of $\\pi$ into $\\mathrm{Ind}_{N_n}^{GL_n}\\psi$",
            "Conductor $Q$: minimal $k$ such that $\\pi$ has a nonzero $\\mathrm{Iw}_k$-fixed vector",
            "Rankin-Selberg integral: $\\Psi(s,W,V) = \\int_{N_n\\backslash GL_n} W\\left(\\begin{smallmatrix}g\\\\&1\\end{smallmatrix}\\right)V(g)|\\det g|^s\\,dg$",
        ],
        "connections": ["Number theory / Langlands program", "q3 (representation theory of combinatorial objects)"],
        "difficulty": (
            "The ramified case is substantially harder than the unramified (spherical) case. "
            "For ramified $\\pi$, the Whittaker function $V$ is not supported on the full Levi subgroup — "
            "the support is concentrated near the conductor translate. Choosing $W$ with the right support "
            "in $\\Pi$ (itself possibly ramified) requires navigating the double coset decomposition "
            "$P_{n}\\backslash GL_{n+1}/P_n$ precisely. The convergence of the integral for all $s$ must also be verified."
        ),
        "boundary_cases": [
            "Unramified $\\pi, \\Pi$: classical result via Casselman-Shalika; the issue is the ramified case",
            "Archimedean case: requires different methods (archimedean Kirillov model is more subtle)",
        ],
        "research_context": (
            "Nelson's work is central to the subconvexity problem for Rankin-Selberg L-functions. "
            "The nonvanishing of local integrals is a key input to the global theta correspondence and "
            "period integral methods (e.g., Waldspurger's formula). The question is also related to "
            "the local Gan-Gross-Prasad conjecture."
        ),
    },
    "q3": {
        "title": r"Problem 3: Markov Chain with Interpolation-Macdonald Stationary Distribution",
        "area": "Algebraic Combinatorics / Integrable Probability",
        "author": "Lauren Williams (Harvard University)",
        "candidate": "**Yes.** A reversible local Markov chain on $S_n(\\lambda)$ has the interpolation-Macdonald distribution as its stationary measure.",
        "strategy": (
            "Define a Markov chain on $S_n(\\lambda) = \\{\\mu: \\mu\\subset\\lambda,\\,|\\mu|=n\\}$ via adjacent transposition proposals. "
            "The transition rates use local product formulas for the ratio $F^*_\\mu / F^*_\\nu$ of interpolation-Macdonald "
            "polynomials at adjacent partitions, obtained from the branching rule for $F^*$ at $q=1$. "
            "Prove: irreducibility (any $\\mu\\in S_n(\\lambda)$ is reachable via adjacent transpositions), "
            "aperiodicity (positive holding probability), and stationarity (detailed balance $\\pi(\\mu)P(\\mu,\\nu) = \\pi(\\nu)P(\\nu,\\mu)$)."
        ),
        "key_theorems": [
            "Interpolation Macdonald polynomials $F^*_\\mu$ (Okounkov 1997, Knop-Sahi 1996)",
            "Branching rule for $F^*$ at $q=1$ (giving local weight ratios)",
            "Perron-Frobenius theorem (unique stationary distribution for irreducible aperiodic chain)",
            "Detailed balance / reversibility criterion",
        ],
        "definitions": [
            "$S_n(\\lambda) = \\{\\mu\\subset\\lambda: |\\mu|=n\\}$: the set of partitions fitting inside $\\lambda$ with $n$ boxes",
            "$F^*_\\mu(x_1,\\ldots,x_k;q,t)$: interpolation Macdonald polynomial (vanishes on a lattice of points indexed by $\\nu\\not\\supset\\mu$)",
            "Adjacent transpositions on $S_n(\\lambda)$: moves that add/remove one box from adjacent rows",
            "Metropolis-Hastings accept probability: $\\min(1, \\pi(\\nu)/\\pi(\\mu))$ for proposal $\\mu\\to\\nu$",
        ],
        "connections": ["q9 (algebraic structure)", "q4 (polynomial combinatorics)", "ASEP / KPZ universality"],
        "difficulty": (
            "The interpolation Macdonald polynomials $F^*_\\mu$ do not have a simple product formula — "
            "they are defined recursively or via a triangular system. Computing the ratio $F^*_\\mu/F^*_\\nu$ "
            "at adjacent partitions requires showing the branching rule gives a purely LOCAL formula. "
            "The nontriviality condition (the chain must actually reach the interpolation-Macdonald distribution, "
            "not some degenerate limit) must be verified, which requires the polynomials to be nonzero on $S_n(\\lambda)$."
        ),
        "boundary_cases": [
            "$q=t$: reduces to ordinary Macdonald polynomials (known case)",
            "$q=0$: Hall-Littlewood case (simpler product formulas)",
            "Empty $\\lambda$: trivial chain",
        ],
        "research_context": (
            "The interpolation Macdonald ASEP is part of a family of integrable stochastic processes "
            "related to the quantum group $U_q(\\widehat{\\mathfrak{gl}}_n)$. Williams' question asks for a "
            "natural Markov chain realizing the stationary measure, analogous to the Robinson-Schensted "
            "dynamics for the ordinary ASEP. This connects to the KPZ universality class and the "
            "algebraic Bethe ansatz."
        ),
    },
    "q4": {
        "title": r"Problem 4: Subharmonicity of $1/\Phi_n$ under Finite Free Convolution",
        "area": "Finite Free Probability / Real-Rooted Polynomials",
        "author": "Nikhil Srivastava (UC Berkeley)",
        "candidate": r"**Yes.** $1/\Phi_n(p\boxplus_n q) \geq 1/\Phi_n(p) + 1/\Phi_n(q)$ for real-rooted $p,q$ of degree $n$.",
        "strategy": (
            r"Identify $\Phi_n(p) = \|\nabla\log\Delta(p)\|^{-2}$ where $\Delta(p) = \prod_{i<j}(\lambda_i-\lambda_j)^2$ is the discriminant. "
            r"The finite-free heat operator $T_\varepsilon = (1-\varepsilon d/dx)^n$ acts on polynomials and contracts roots. "
            r"Along the heat flow, $\Phi_n$ satisfies a differential inequality analogous to the classical "
            r"Fisher-information inequality. The key is: "
            r"(1) derive $\frac{d}{d\varepsilon}\Phi_n(T_\varepsilon p) = -2\Phi_n(p)^2 \sum_{i\neq j}(\lambda_i-\lambda_j)^{-2}$; "
            r"(2) use convexity of $1/\Phi_n$ along the finite-free convolution path to conclude subadditivity."
        ),
        "key_theorems": [
            r"Marcus-Spielman-Srivastava theorem (Kadison-Singer / interlacing families)",
            r"Finite free convolution $\boxplus_n$: coefficient-wise definition via $\mathbb{E}[p\cdot q]$ for random roots",
            r"Fisher information inequality (classical: $1/I(X+Y)\geq 1/I(X)+1/I(Y)$)",
            r"Stam inequality for free probability (free analogue of Fisher information subadditivity)",
        ],
        "definitions": [
            r"Real-rooted polynomial: $p(x) = \prod_{i=1}^n(x-\lambda_i)$ with all $\lambda_i\in\mathbb{R}$",
            r"Finite free convolution $p\boxplus_n q$: the unique degree-$n$ polynomial whose $k$-th coefficient equals $\mathbb{E}[p(U)q(V)]$ for independent Haar-random unitaries $U,V$",
            r"Finite Fisher information: $\Phi_n(p) = \|\text{score}(p)\|^2$ where score$_i = \sum_{j\neq i}(\lambda_i-\lambda_j)^{-1}$",
            r"Finite-free heat flow: $T_\varepsilon p = (1-\varepsilon d/dx)^n p$ (contracts roots toward origin)",
        ],
        "connections": [
            "q6 (spectral methods / Marcus-Spielman-Srivastava)",
            "q1 (heat flow + measure theory)",
            "q3 (polynomial combinatorics)",
        ],
        "difficulty": (
            r"The finite free convolution $\boxplus_n$ lacks a free Fourier transform or $R$-transform — "
            r"it is defined combinatorially and does not have the same analytic machinery as classical or free convolution. "
            r"The differential identity for $\Phi_n$ along the heat flow is subtle because the roots $\lambda_i(t)$ "
            r"move continuously but may collide (double roots), and $\Phi_n=\infty$ at multiple roots. "
            r"An approximation argument via simple-root polynomials is needed to handle this boundary case."
        ),
        "boundary_cases": [
            r"Multiple roots: $\Phi_n=\infty$ by convention; need continuity of the inequality",
            r"$\varepsilon\to0$ (one factor is $\delta_0^n$): reduces to $\Phi_n(p\boxplus_n\delta^n)\geq\Phi_n(p)$",
        ],
        "research_context": (
            "This is part of Srivastava's program to understand the finite free probability analogue "
            "of entropic CLT and Fisher information inequalities. The Marcus-Spielman-Srivastava theorem "
            "(proving Kadison-Singer) used interlacing families — a finite-dimensional analogue of free independence. "
            "This question asks whether the standard information-theoretic inequalities carry over."
        ),
    },
    "q5": {
        "title": r"Problem 5: $\mathcal{O}$-Adapted Slice Filtration for $N_\infty$ Operads",
        "area": "Equivariant Stable Homotopy Theory",
        "author": "Andrew Blumberg (Columbia University)",
        "candidate": r"**Yes.** Define the $\mathcal{O}$-slice filtration via admissible geometric fixed-point connectivities; characterize it by the transfer system of $\mathcal{O}$.",
        "strategy": (
            r"Given an $N_\infty$ operad $\mathcal{O}$ with transfer system $\mathcal{T}(\mathcal{O})$, "
            r"define $\mathcal{O}$-slice cells as $G$-spectra of the form $G/H_+\wedge S^{nV}$ where $H\in\mathcal{T}(\mathcal{O})$. "
            r"The $\mathcal{O}$-slice filtration $\tau_{\geq n}^{\mathcal{O}}$ is the localizing subcategory generated by these cells. "
            r"Characterization: $X$ is $\mathcal{O}$-slice $\geq n$ iff for all $H\leq G$ with $H\in\mathcal{T}(\mathcal{O})$, "
            r"$\Phi^H X$ is $(n/|G/H|)$-connective. Prove both directions by checking generators and closure under cofibers."
        ),
        "key_theorems": [
            r"Hill-Hopkins-Ravenel slice filtration (classical slice tower for $G$-spectra)",
            r"Geometric fixed points $\Phi^H$: smashing localization away from $H$-free spectra",
            r"Transfer system of $N_\infty$ operad (encodes which norms are available)",
            r"Freeness criterion for $G$-spectra (when $\Phi^H X \simeq 0$)",
        ],
        "definitions": [
            r"$N_\infty$ operad $\mathcal{O}$: $G$-operad encoding a partial system of multiplicative transfers",
            r"Transfer system $\mathcal{T}(\mathcal{O})$: the collection of $H\leq K\leq G$ for which $H$-to-$K$ norm exists in $\mathcal{O}$",
            r"$\mathcal{O}$-slice cell: $G/H_+\wedge S^{nV}$ for $H\in\mathcal{T}(\mathcal{O})$, $V$ a $G/H$-representation",
            r"Geometric fixed points $\Phi^H X = (X\wedge\tilde{E}\mathcal{F}[H])^H$: extracts the $H$-fixed part modulo proper subgroups",
        ],
        "connections": ["q7 (equivariant topology / group actions)", "q8 (filtered structures in geometry)"],
        "difficulty": (
            r"$N_\infty$ operads interpolate between $E_\infty$ (all transfers) and $A_\infty$ (no transfers). "
            r"The slice filtration must be defined so that it is: (a) compatible with the $\mathcal{O}$-algebra structure, "
            r"(b) recovers the HHR filtration when $\mathcal{O}=E_\infty$, "
            r"(c) characterized by a checkable connectivity condition. "
            r"The main difficulty is verifying the fixed-point characterization for all subgroups simultaneously, "
            r"especially for subgroups NOT in the transfer system."
        ),
        "boundary_cases": [
            r"$\mathcal{O}=E_\infty$: recover the classical HHR slice filtration",
            r"$\mathcal{O}=A_\infty$ (no transfers): the $\mathcal{O}$-slice filtration should collapse to the Postnikov tower",
        ],
        "research_context": (
            r"Blumberg-Hill classified $N_\infty$ operads for $C_{p^n}$ in terms of their transfer systems, "
            r"showing there are $2^{n-1}$ distinct equivariant multiplications. "
            r"This question asks for the slice tower adapted to a given intermediate multiplication structure. "
            r"The application is to Real topological K-theory and Real bordism spectra."
        ),
    },
    "q6": {
        "title": r"Problem 6: $\varepsilon$-Light Subsets in Graphs",
        "area": "Spectral Graph Theory",
        "author": "Daniel Spielman (Yale University)",
        "candidate": r"**Yes.** There exists $c = 1/(3C) > 0$ (universal) such that every graph $G$ and $\varepsilon\in[0,1]$ admit an $\varepsilon$-light subset $S\subseteq V$ with $|S|\geq c\varepsilon|V|$.",
        "strategy": (
            r"**Step 1 (Paving).** Apply the spectral vertex paving theorem: there exists a universal $C>0$ such that "
            r"for any graph $G$ with Laplacian $L$, the vertex set $V$ can be partitioned $V=S_1\sqcup\cdots\sqcup S_r$ "
            r"with $L_{S_i}\preceq (C/r)L$ for all $i$, where $r$ is any positive integer. "
            r"**Step 2 (Choice of $r$).** Set $r = \lceil 2C/\varepsilon\rceil$, so $C/r \leq \varepsilon/2 < \varepsilon$. "
            r"Then every part $S_i$ is $\varepsilon$-light. "
            r"**Step 3 (Averaging).** By pigeonhole, the largest part has $|S_i|\geq |V|/r \geq \varepsilon|V|/(3C)$. "
            r"**Conclusion.** Take $c = 1/(3C)$."
        ),
        "key_theorems": [
            r"Spectral vertex paving theorem: $\forall r\,\exists$ partition of $V$ with $L_{S_i}\preceq (C/r)L$ (follows from Kadison-Singer / MSS theorem)",
            r"Marcus-Spielman-Srivastava theorem (2015): every paving conjecture holds with $C\leq 18$",
            r"Positive semidefinite order on symmetric matrices: $A\preceq B\iff B-A$ is PSD",
            r"Courant minimax principle: eigenvalues of $L_{S_i}$ interlace those of $L$ under the PSD order",
        ],
        "definitions": [
            r"Graph Laplacian $L$: $L_{vv}=\deg(v)$, $L_{vw}=-\mathbf{1}[vw\in E]$; PSD, $\ker L =$ constant functions on each component",
            r"Induced subgraph Laplacian $L_S$: Laplacian of $G_S=(V, E(S,S))$; zero outside $S\times S$",
            r"$\varepsilon$-light set $S$: $L_S\preceq\varepsilon L$, i.e., $x^TL_Sx\leq\varepsilon\,x^TLx$ for all $x\in\mathbb{R}^V$",
            r"Paving constant $C$: the universal constant in the vertex paving theorem; best known $C\leq 18$",
        ],
        "connections": ["q4 (MSS theorem is shared tool)", "q9 (PSD matrix structure)", "Kadison-Singer conjecture (now theorem)"],
        "difficulty": (
            r"The paving theorem itself (used as a black box here) is the hard part — it is equivalent to Kadison-Singer, "
            r"proved by Marcus-Spielman-Srivastava in 2015 using the method of interlacing polynomials. "
            r"Within the proof of this problem, the key subtleties are: "
            r"(a) verifying the paving theorem applies to all finite graphs including disconnected ones and the empty graph; "
            r"(b) the boundary cases $\varepsilon=0$ (trivially, $S=\emptyset$) and $\varepsilon=1$ (trivially, $S=V$); "
            r"(c) the constant $c=1/(3C)$ is believed far from tight — the conjecture is $c=1/2$."
        ),
        "boundary_cases": [
            r"$\varepsilon=0$: the only $0$-light set is $\emptyset$; the statement holds trivially with $S=\emptyset$",
            r"$\varepsilon=1$: every $S\subseteq V$ is $1$-light (since $L_S\preceq L$ always); take $S=V$",
            r"Disconnected $G$: the paving theorem applies component-by-component; the bound $c=1/(3C)$ still holds",
            r"Empty graph ($E=\emptyset$): $L=0$, every set is $\varepsilon$-light for all $\varepsilon$",
            r"Complete graph $K_n$: $L = nI - J$; here $c=1/2$ should be achievable by explicit construction",
        ],
        "research_context": (
            r"Spielman conjectures the tight constant is $c=1/2$, achieved (asymptotically) by the complete graph. "
            r"This is related to the Weaver $\mathrm{KS}_2$ problem and to spectral sparsification. "
            r"The $\varepsilon$-light condition captures how much of the graph's spectral energy a subset 'contains'; "
            r"light subsets are spectrally dominated by the full graph. "
            r"Applications: graph partitioning, spectral sparsifiers, quantum information (paving of frames)."
        ),
    },
    "q7": {
        "title": r"Problem 7: Compact Manifolds with 2-Torsion Uniform Lattice",
        "area": "Lattices in Lie Groups / Geometric Topology",
        "author": "Shmuel Weinberger (University of Chicago)",
        "candidate": r"**No.** No compact Riemannian manifold $M$ has $\pi_1(M)$ a uniform lattice $\Gamma$ with nontrivial 2-torsion of a specified type.",
        "strategy": (
            r"Assume $M$ is a compact aspherical manifold with $\pi_1(M)=\Gamma$ containing an element $\gamma$ of order 2. "
            r"The element $\gamma$ acts freely on the universal cover $\tilde{M}$ (deck transformation $\neq\mathrm{id}$ is fixed-point-free). "
            r"Apply Smith theory: for a $\mathbb{Z}/2\mathbb{Z}$ action on a space $X$ rationally acyclic in the right range, "
            r"the fixed-point set $X^{\mathbb{Z}/2\mathbb{Z}}$ is nonempty. "
            r"But a free action has no fixed points — contradiction."
        ),
        "key_theorems": [
            r"Smith fixed-point theorem: $(\mathbb{Z}/p\mathbb{Z})$-action on $\mathbb{Z}/p$-acyclic space has nonempty fixed set",
            r"Borel formula: $\chi(M) = \chi(M/\gamma)\cdot|\langle\gamma\rangle|$ for free actions",
            r"Asphericity: $M$ aspherical iff $\tilde{M}$ is contractible (i.e., $\tilde{M}\simeq*$)",
            r"Deck transformation group $\cong\pi_1(M)$: acts freely and properly discontinuously on $\tilde{M}$",
        ],
        "definitions": [
            r"Uniform lattice $\Gamma$ in $G$: discrete subgroup with $G/\Gamma$ compact",
            r"2-torsion: element $\gamma\in\Gamma$ with $\gamma^2=e$, $\gamma\neq e$",
            r"Aspherical manifold: $M$ with $\pi_k(M)=0$ for $k\geq 2$ (equivalently, $\tilde{M}$ contractible)",
            r"Smith theory fixed-point set $X^G$: the set of points fixed by all $g\in G$",
        ],
        "connections": ["q5 (equivariant homotopy)", "q8 (manifold obstructions)"],
        "difficulty": (
            r"The precise hypotheses of Smith theory must be verified: the universal cover $\tilde{M}$ must be "
            r"$\mathbb{Z}/2$-acyclic in the right range. For an aspherical manifold, $\tilde{M}$ is contractible, "
            r"hence acyclic over any ring. But Smith theory requires the space to have the right *finite* homology; "
            r"infinite-dimensional contractible spaces require careful treatment. "
            r"The specific statement of Weinberger's problem may involve additional hypotheses on $\Gamma$ "
            r"(e.g., as a lattice in a specific Lie group) that change which version of Smith theory applies."
        ),
        "boundary_cases": [
            r"$\Gamma$ torsion-free: the question is vacuous (no 2-torsion); all known examples of aspherical manifolds",
            r"$\Gamma = \mathbb{Z}/2\mathbb{Z}$: trivial lattice; $M = \mathbb{RP}^n$, which has 2-torsion but is not aspherical for $n\geq 2$",
        ],
        "research_context": (
            r"This is related to the Borel conjecture (aspherical manifolds are determined by their fundamental group) "
            r"and the Farrell-Jones conjecture (algebraic K- and L-theory of group rings). "
            r"Weinberger's problem tests whether lattices with 2-torsion can appear as fundamental groups of aspherical manifolds, "
            r"which would have implications for the topology of locally symmetric spaces."
        ),
    },
    "q8": {
        "title": r"Problem 8: Lagrangian Smoothings of Polyhedral Lagrangians",
        "area": "Symplectic Geometry",
        "author": "Mohammed Abouzaid (Columbia University)",
        "candidate": r"**No** in general. A four-face vertex obstruction via Maslov index prevents Lagrangian smoothing.",
        "strategy": (
            r"A polyhedral Lagrangian $L\subset(M,\omega)$ is a piecewise-linear Lagrangian submanifold. "
            r"Near each vertex $v$, the local model is $k$ Lagrangian half-planes in $(T_vM,\omega_v)\cong(\mathbb{R}^{2n},\omega_0)$ meeting at $v$. "
            r"A smoothing at $v$ requires an exact Lagrangian disk filling the Legendrian link $\Lambda_v\subset S^{2n-1}$ "
            r"(the intersection of $L$ with a small sphere around $v$). "
            r"For $k=4$ planes in specific configuration, compute the Maslov index of the Legendrian link; "
            r"show it obstructs an exact Lagrangian filling by the Ekholm-Honda-Kálmán criterion."
        ),
        "key_theorems": [
            r"Lagrangian neighborhood theorem: $L\subset M$ has a tubular neighborhood $\cong T^*L$",
            r"Maslov index of a Legendrian knot: the rotation number of the tangent frame along the knot",
            r"Ekholm-Honda-Kálmán: obstructions to exact Lagrangian fillings from linearized Legendrian contact homology",
            r"Polterovich-Shelukhin: Hamiltonian isotopy invariance of symplectic capacities",
        ],
        "definitions": [
            r"Lagrangian submanifold $L\subset(M^{2n},\omega)$: $\dim L=n$ and $\omega|_L=0$",
            r"Polyhedral Lagrangian: $L$ is piecewise-smooth, with faces that are smooth Lagrangians and vertices where faces meet",
            r"Legendrian link $\Lambda_v$: intersection of $L$ with a small contact sphere $(S^{2n-1}_\varepsilon(v),\xi)$ around vertex $v$",
            r"Exact Lagrangian filling of $\Lambda$: a compact Lagrangian $F\subset(\mathbb{R}^{2n},\lambda_0)$ with $\partial F=\Lambda$ and $\lambda_0|_F$ exact",
            r"Maslov class: an element of $H^1(L;\mathbb{Z})$ measuring the winding of the tangent plane",
        ],
        "connections": ["q5 (filtered structures in topology)", "q7 (topological obstructions)"],
        "difficulty": (
            r"Computing Legendrian contact homology for the vertex link requires understanding the pseudo-holomorphic "
            r"curve count in the symplectization $\Lambda\times\mathbb{R}$. For generic four-face vertices, "
            r"this computation can be done combinatorially using the front projection, but identifying the "
            r"correct configuration that is obstructed requires careful case analysis. "
            r"The Hamiltonian isotopy invariance of the obstruction must also be verified."
        ),
        "boundary_cases": [
            r"$k=2$ planes (edge vertex): always smoothable (by the $h$-principle for Lagrangians near boundary)",
            r"$k=3$ planes: partially understood; some configurations are smoothable",
            r"$k=4$ planes in 'generic' position: the claim is this is obstructed",
        ],
        "research_context": (
            r"Abouzaid's work on Lagrangian cobordisms and the Fukaya category motivates this question. "
            r"Polyhedral Lagrangians arise naturally as tropical limits of smooth Lagrangians in mirror symmetry. "
            r"Whether they can be smoothed is related to the question of which tropical cycles are representable "
            r"by smooth Lagrangians, with applications to homological mirror symmetry."
        ),
    },
    "q9": {
        "title": r"Problem 9: Algebraic Relations on Determinantal Tensors",
        "area": "Algebraic Geometry / Tensor Invariants",
        "author": "Joe Kileel (UT Austin)",
        "candidate": r"**Yes.** There exists a finite set $\mathbf{F}$ of bounded-degree polynomial equations cutting out the locus of determinantal tensors up to scaling.",
        "strategy": (
            r"The determinantal tensor $Q^{(\alpha\beta\gamma\delta)} = \det\begin{pmatrix}A_\alpha\\B_\beta\\C_\gamma\\D_\delta\end{pmatrix}$ "
            r"for generic row matrices $A,B,C,D$. The scaling locus is defined by "
            r"$Q^{(\alpha\beta\gamma\delta)} = u_\alpha v_\beta w_\gamma x_\delta$ for some $(u,v,w,x)$. "
            r"This is the variety of rank-1 tensors in a specific coordinate system. "
            r"The defining equations are the $2\times 2$ minors of the flattenings of $Q$: "
            r"$Q^{(\alpha\beta)(\gamma\delta)}\cdot Q^{(\alpha'\beta')(\gamma'\delta')} = Q^{(\alpha\beta)(\gamma'\delta')}\cdot Q^{(\alpha'\beta')(\gamma\delta)}$. "
            r"These are bounded-degree (degree 2) binomials generating the toric ideal."
        ),
        "key_theorems": [
            r"Fundamental theorem of projective algebraic geometry: the ideal of a variety is generated by its lowest-degree elements (for toric varieties, by binomials)",
            r"Hochster-Huneke: toric ideals of normal toric varieties are generated in degree $\leq$ dimension",
            r"Cauchy-Binet formula: $\det(AB) = \sum_S\det(A_S)\det(B_S)$ (gives the structure of $Q$)",
            r"Generic identifiability: for Zariski-generic row matrices, $Q$ determines $(A,B,C,D)$ up to gauge",
        ],
        "definitions": [
            r"Determinantal tensor $Q$: $Q^{(\alpha\beta\gamma\delta)} = \det\begin{pmatrix}A_\alpha\\B_\beta\\C_\gamma\\D_\delta\end{pmatrix}$ for row vectors $A_\alpha\in\mathbb{R}^d$",
            r"Scaling locus: $\{Q: Q^{(\alpha\beta\gamma\delta)} = u_\alpha v_\beta w_\gamma x_\delta\text{ for some }u,v,w,x\}$ (rank-1 tensors in disguise)",
            r"Toric ideal of the complete 4-partite model: ideal of $2\times 2$ minors of all flattenings of $Q$",
            r"Bounded-degree generators: polynomial equations of degree $\leq D$ for some universal $D$",
        ],
        "connections": ["q10 (tensor decomposition / numerical methods)", "q3 (algebraic combinatorics of symmetric functions)"],
        "difficulty": (
            r"The determinantal tensors do NOT form a linear subspace — they are the image of a nonlinear map "
            r"(the determinant). Identifying which polynomial equations cut out this image requires understanding "
            r"the Zariski closure of the image, which may have components not visible from generic points. "
            r"Verifying that the toric binomials actually generate the ideal (vs. just vanishing on it) requires "
            r"a Gröbner basis computation or algebraic geometry argument."
        ),
        "boundary_cases": [
            r"Rank-1 row matrices ($d=1$): $Q$ is always a product tensor; the ideal is trivially generated by $2\times 2$ minors",
            r"Non-generic $A,B,C,D$: the map $A,B,C,D\mapsto Q$ may fail to be injective; identifiability breaks down",
        ],
        "research_context": (
            r"This problem is motivated by algebraic statistics (phylogenetic models), computer vision (structure from motion), "
            r"and signal processing (BSS / ICA). Kileel's work on chordal varieties and tensor decompositions provides "
            r"the framework. The question asks for explicit, checkable algebraic certificates of the determinantal structure."
        ),
    },
    "q10": {
        "title": r"Problem 10: PCG for RKHS-CP Decomposition",
        "area": "Numerical Linear Algebra / Kernel Methods",
        "author": "Tamara Kolda (MathSci.ai) and Rachel Ward (UT Austin)",
        "candidate": r"**Yes.** PCG with an RKHS-aware preconditioner solves the CP normal equations in $O(qr + nr^2 + r\cdot\text{cost}(K\text{-multiply}))$ per iteration, avoiding $O(N)$ and $O(M)$ costs.",
        "strategy": (
            r"The RKHS-CP model: minimize $\|P_\Omega(KXZ^T) - P_\Omega(Y)\|_F^2 + \lambda\|X\|_K^2$ "
            r"where $P_\Omega$ is the observation mask, $K$ is the kernel matrix ($n\times n$), and $Z\in\mathbb{R}^{q\times r}$. "
            r"**Normal equations:** $(Z\otimes K)^T P_\Omega (Z\otimes K)\,\text{vec}(X) + \lambda(I_r\otimes K)\,\text{vec}(X) = (Z\otimes K)^T\text{vec}(P_\Omega Y)$. "
            r"**Key insight:** never form $Z\otimes K$ explicitly. Instead, given $x=\text{vec}(X)$: "
            r"compute $(Z\otimes K)x$ by $KXZ^T$, apply mask $P_\Omega$, apply transpose. Cost: $O(nr^2 + r\cdot\text{cost}(K))$. "
            r"**Preconditioner:** $(Z^TZ+\lambda I_r)\otimes K$ or its diagonal/block approximation — cheap to apply (same cost)."
        ),
        "key_theorems": [
            r"Conjugate gradient convergence: $O(\sqrt{\kappa(A)}\log(1/\varepsilon))$ iterations for $\kappa=\lambda_{\max}/\lambda_{\min}$",
            r"Kronecker product identity: $(A\otimes B)(C\otimes D) = (AC)\otimes(BD)$",
            r"RKHS representer theorem: optimal $f = \sum_i\alpha_i K(x_i,\cdot)$, i.e., $X = K\alpha$ for some coefficient matrix",
            r"Nystrom approximation: $K\approx K_{nm}K_{mm}^{-1}K_{nm}^T$ for cheap approximate kernel-vector products",
        ],
        "definitions": [
            r"RKHS-CP model: $f(x,z) = \sum_{j=1}^r f_j(x)z_j$ with $f_j\in\mathcal{H}_K$ (kernel Hilbert space)",
            r"Observation mask $P_\Omega$: projects to the $|\Omega|$ observed entries (not all $N=n\cdot q$ entries)",
            r"Normal equation operator $\mathcal{A}$: $\mathcal{A}X = \sum_{(i,j)\in\Omega}(KX_{i\cdot})(Z_{j\cdot})(Z_{j\cdot})^T + \lambda KX$",
            r"SPD of $\mathcal{A}$: guaranteed by $\lambda > 0$ and $K\succ 0$, enabling CG",
        ],
        "connections": ["q9 (tensor structure)", "q4 (spectral methods for matrices)"],
        "difficulty": (
            r"The matrix $Z\otimes K$ is $nr\times nr$ and cannot be formed explicitly. "
            r"The challenge is implementing the matrix-vector product $x\mapsto\mathcal{A}x$ implicitly using only $|\Omega|$ observed entries "
            r"(not all $N=nq$ entries or $M=qr$ factor entries). The preconditioner must: "
            r"(a) be cheap to apply (no dense factorizations), "
            r"(b) adequately approximate $\mathcal{A}$ so CG converges in few iterations, "
            r"(c) be provably SPD to guarantee CG termination."
        ),
        "boundary_cases": [
            r"Fully observed ($\Omega = [n]\times[q]$): reduces to standard Kronecker-structured least squares",
            r"$r=1$ (rank-1 model): simplifies to standard RKHS regression",
            r"$\lambda\to 0$: system becomes singular (need regularization); CG diverges",
        ],
        "research_context": (
            r"RKHS-CP decomposition combines kernel methods (for capturing nonlinear structure in $x$) "
            r"with CP (PARAFAC) tensor decomposition (for low-rank structure in the $(x,z)$ interaction). "
            r"Applications: multi-task learning, collaborative filtering with kernel similarity, "
            r"spatiotemporal data analysis. The PCG approach connects to scalable kernel methods "
            r"(random features, Nyström) and randomized linear algebra."
        ),
    },
}


# ── Directory helpers ─────────────────────────────────────────────────────────

def question_dir(repo_root: Path, problem_id: str) -> Path:
    d = repo_root / "documents" / "questions" / problem_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def discussions_dir(repo_root: Path) -> Path:
    d = repo_root / "documents" / "discussions"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Data helpers ──────────────────────────────────────────────────────────────

def _read_problem_tex(repo_root: Path, problem_id: str) -> tuple[str, str, str]:
    tex = repo_root / "problems" / f"{problem_id}.tex"
    if not tex.is_file():
        return ("", "", "")
    text = tex.read_text(encoding="utf-8", errors="replace")
    title_m = re.search(r"\\title\{(.+?)\}", text, re.DOTALL)
    author_m = re.search(r"\\author\{(.+?)\}", text, re.DOTALL)
    body_m = re.search(r"\\maketitle\s*(.*?)\\end\{document\}", text, re.DOTALL)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    author = re.sub(r"\s+", " ", author_m.group(1)).strip() if author_m else ""
    body = body_m.group(1).strip() if body_m else ""
    return title, author, body


def _load_attempts(repo_root: Path, problem_id: str) -> list[dict]:
    mem = repo_root / "documents" / "strategy_memory.jsonl"
    if not mem.is_file():
        return []
    entries = []
    for line in mem.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("problem_id") == problem_id:
            entries.append(e)
    return entries


def _load_issues(repo_root: Path, problem_id: str) -> list[dict]:
    try:
        from .issues import list_issues
        return list_issues(repo_root, problem_id)
    except Exception:
        return []


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _status_emoji(attempts: list[dict]) -> str:
    if not attempts:
        return "⚪ Not Started"
    if any(e.get("outcome") == "success" for e in attempts):
        return "✅ Solved"
    min_issues = min(e.get("issue_count", 99) for e in attempts)
    if min_issues <= 2:
        return "🟡 Near-Complete"
    if min_issues <= 5:
        return "🟠 Partial Progress"
    return "🔴 Open"


# ── overview.md ───────────────────────────────────────────────────────────────

def write_overview(repo_root: Path, problem_id: str) -> Path:
    """Static deep background document. Written once; updated manually."""
    p = PROFILES.get(problem_id, {})
    _, _, statement_body = _read_problem_tex(repo_root, problem_id)
    out = question_dir(repo_root, problem_id) / "overview.md"

    key_theorems = "\n".join(f"- {t}" for t in p.get("key_theorems", []))
    definitions_block = "\n".join(
        f"- **{d.split(':')[0].strip()}**: {':'.join(d.split(':')[1:]).strip()}"
        if ':' in d else f"- {d}"
        for d in p.get("definitions", [])
    )
    connections_block = "\n".join(f"- {c}" for c in p.get("connections", []))
    boundary_cases_block = "\n".join(f"- {b}" for b in p.get("boundary_cases", []))

    doc = f"""# {p.get('title', problem_id.upper())} — Overview

**Problem ID:** `{problem_id}` | **Area:** {p.get('area', '')}
**Author:** {p.get('author', '')}

> This document is the **static reference** for {problem_id.upper()}.
> It covers background, definitions, key tools, and why the problem is hard.
> For live progress and attempt history, see [`progress.md`](progress.md) and [`timeline.md`](timeline.md).

---

## Problem Statement

```latex
{statement_body[:4000]}
```

---

## Mathematical Background

### Area and Context

{p.get('area', '')}. {p.get('research_context', '')}

### Key Definitions

{definitions_block}

### Key Theorems and Tools

{key_theorems}

### Candidate Answer

{p.get('candidate', '')}

### Core Construction / Proof Idea

{p.get('strategy', '')}

---

## Why This Problem Is Hard

{p.get('difficulty', '_Difficulty analysis not yet written._')}

---

## Boundary Cases to Handle

{boundary_cases_block}

---

## Connections to Other Benchmark Problems

{connections_block}

---

## Research Context and Significance

{p.get('research_context', '_Research context not yet written._')}

---

*This document is stable reference material. Updates reflect improved understanding of the problem, not run results.*
*For attempt history see [`timeline.md`](timeline.md). For current status see [`progress.md`](progress.md).*
"""
    out.write_text(doc, encoding="utf-8")
    return out


# ── timeline.md ───────────────────────────────────────────────────────────────

def update_timeline(repo_root: Path, problem_id: str) -> Path:
    """Chronological log of all attempts. Fully regenerated from memory.jsonl."""
    attempts = _load_attempts(repo_root, problem_id)
    out = question_dir(repo_root, problem_id) / "timeline.md"

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for a in attempts:
        date = a.get("date", "unknown")
        by_date.setdefault(date, []).append(a)

    total = len(attempts)
    successes = sum(1 for a in attempts if a.get("outcome") == "success")
    fails = sum(1 for a in attempts if a.get("outcome") == "fail")
    best_issues = min((a.get("issue_count", 99) for a in attempts), default=None)

    # Summary table (all attempts)
    table_rows = []
    for i, a in enumerate(attempts, 1):
        icon = "✅" if a.get("outcome") == "success" else "❌" if a.get("outcome") == "fail" else "⚠️"
        strategy_short = (a.get("strategy", "")[:55] + "…") if len(a.get("strategy", "")) > 55 else a.get("strategy", "")
        table_rows.append(
            f"| {i} | {a.get('date','?')} | {a.get('model','skeleton')} | "
            f"{icon} {a.get('outcome','?')} | {a.get('issue_count','?')} | {strategy_short} |"
        )

    table = "\n".join(table_rows) if table_rows else "_No attempts recorded yet._"

    # Detailed dated sections
    dated_sections = []
    for date in sorted(by_date.keys(), reverse=True):
        day_attempts = by_date[date]
        section_lines = [f"## {date}", ""]
        for j, a in enumerate(day_attempts, 1):
            icon = "✅" if a.get("outcome") == "success" else "❌"
            section_lines += [
                f"### Attempt — {a.get('model', 'skeleton')} — {icon} {a.get('outcome', '?')}",
                "",
                f"**Strategy:**",
                f"> {a.get('strategy', '')}",
                "",
                f"**Outcome:** {a.get('outcome', '?')} | **Verifier issues:** {a.get('issue_count', '?')}",
            ]
            if a.get("notes"):
                section_lines += ["", f"**Notes:** {a['notes']}"]
            section_lines.append("")
        dated_sections.append("\n".join(section_lines))

    doc = f"""# {problem_id.upper()}: Attempt Timeline

**Total attempts:** {total} | **Successes:** {successes} | **Failures:** {fails}
**Best result:** {f'{best_issues} verifier issues' if best_issues is not None else 'no attempts yet'}
**Last updated:** {_now()}

> This document records every proof attempt in chronological order.
> Each entry shows the model, strategy used, and verifier outcome.

---

## Summary Table

| # | Date | Model | Outcome | Issues | Strategy |
|---|------|-------|---------|--------|----------|
{table}

---

## Detailed Attempt Log

{chr(10).join(dated_sections) if dated_sections else '_No attempts recorded yet._'}

---

*Auto-generated from `documents/strategy_memory.jsonl`. New entries appear after each `rma solve` run.*
"""
    out.write_text(doc, encoding="utf-8")
    return out


# ── progress.md ───────────────────────────────────────────────────────────────

def update_progress(
    repo_root: Path,
    problem_id: str,
    reasoning_trace: str = "",
    model_used: str = "",
    run_outcome: str = "",
) -> Path:
    """Live current-status document. Updated after every run."""
    p = PROFILES.get(problem_id, {})
    attempts = _load_attempts(repo_root, problem_id)
    issues = _load_issues(repo_root, problem_id)
    out = question_dir(repo_root, problem_id) / "progress.md"

    status = _status_emoji(attempts)
    total = len(attempts)
    successes = sum(1 for a in attempts if a.get("outcome") == "success")
    best_issues = min((a.get("issue_count", 99) for a in attempts), default=None)

    # Best attempt so far
    best_attempt = None
    if attempts:
        best_attempt = min(attempts, key=lambda a: a.get("issue_count", 99))

    # Open issues
    open_issues = [i for i in issues if i.get("status") in ("open", "in_progress")]
    resolved_issues = [i for i in issues if i.get("status") == "resolved"]

    open_block = ""
    for iss in open_issues:
        comments = iss.get("comments", [])
        last_comment = comments[-1].get("body", "")[:300] if comments else ""
        open_block += f"\n### 🔴 [{iss['id']}] {iss.get('title', '')}\n**Status:** {iss.get('status')} | **Labels:** {', '.join(iss.get('labels', []))}\n\n{last_comment}\n"

    resolved_block = "\n".join(
        f"- ✅ [{i['id']}] {i.get('title','')}" for i in resolved_issues
    ) or "_None yet._"

    # Trace excerpt (last 100 lines)
    trace_block = ""
    if reasoning_trace.strip():
        lines = reasoning_trace.strip().splitlines()
        excerpt = lines[-100:] if len(lines) > 100 else lines
        if len(lines) > 100:
            excerpt = [f"_(showing last 100 of {len(lines)} lines)_", ""] + excerpt
        trace_block = "\n".join(excerpt)

    # What's been established / what's open
    established = []
    open_gaps = []
    if best_attempt and best_attempt.get("issue_count", 99) < 9:
        established.append("Proof skeleton generated and partially verified")
    else:
        open_gaps += [
            "Complete proof has not passed all verifier checks",
            "Hypothesis audit for key theorems not yet included",
            "Boundary cases need explicit case analysis",
        ]

    established_block = "\n".join(f"- {e}" for e in established) or "_Nothing formally established yet — all attempts failed verification._"
    gaps_block = "\n".join(f"- {g}" for g in open_gaps) or "_No gaps identified — problem may be solved._"

    # Next steps
    next_steps = []
    if not any(a.get("model", "") not in ("rma-skeleton", "") for a in attempts):
        next_steps.append("Run with a real model (claude-opus-4-8 or claude-sonnet-4-6) — all current attempts used the skeleton model")
    next_steps += [
        "Try `--strategies 3` to explore multiple proof approaches in parallel",
        "Run the issue discovery agent to identify specific mathematical gaps",
        "Check the overview.md for untried proof strategies",
    ]

    doc = f"""# {problem_id.upper()}: Current Progress

**Status:** {status}
**Last updated:** {_now()} | **Last model run:** {model_used or 'none'} ({run_outcome or 'n/a'})
**Total attempts:** {total} | **Successes:** {successes} | **Best:** {f'{best_issues} verifier issues' if best_issues is not None else 'no data'}

> **Quick links:** [Overview](overview.md) | [Timeline](timeline.md) | [Strategies](strategies.md)

---

## Current Status

{status}

{"### Best Attempt So Far" if best_attempt else ""}
{"" if not best_attempt else f'''**Model:** {best_attempt.get('model','skeleton')} | **Date:** {best_attempt.get('date','')} | **Issues:** {best_attempt.get('issue_count','?')}
**Strategy used:**
> {best_attempt.get('strategy','')}'''}

---

## What Has Been Established

{established_block}

## What Remains Open

{gaps_block}

---

## Issues

### Open ({len(open_issues)})

{open_block if open_block else '_No open issues._'}

### Resolved ({len(resolved_issues)})

{resolved_block}

---

## Latest Agent Reasoning Trace

{"**Model:** " + model_used + " | **Outcome:** " + run_outcome if model_used else "_No agent run in this update._"}

{"```" + chr(10) + trace_block + chr(10) + "```" if trace_block else "_No transcript available._"}

---

## Recommended Next Steps

{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(next_steps))}

---

*Auto-updated after every `rma solve` or daily agent run.*
*See [`timeline.md`](timeline.md) for full attempt history.*
"""
    out.write_text(doc, encoding="utf-8")
    return out


# ── strategies.md ─────────────────────────────────────────────────────────────

def update_strategies(repo_root: Path, problem_id: str) -> Path:
    """Strategy space document. Updated as new attempts are made."""
    p = PROFILES.get(problem_id, {})
    attempts = _load_attempts(repo_root, problem_id)
    out = question_dir(repo_root, problem_id) / "strategies.md"

    # Deduplicate strategies tried
    tried: dict[str, dict] = {}
    for a in attempts:
        key = a.get("strategy", "")[:80]
        if key not in tried or a.get("issue_count", 99) < tried[key].get("best_issues", 99):
            tried[key] = {
                "strategy": a.get("strategy", ""),
                "best_issues": a.get("issue_count", 99),
                "outcome": a.get("outcome", ""),
                "model": a.get("model", ""),
                "count": tried.get(key, {}).get("count", 0) + 1,
            }

    tried_block = ""
    for entry in sorted(tried.values(), key=lambda x: x["best_issues"]):
        icon = "✅" if entry["outcome"] == "success" else "❌"
        tried_block += (
            f"\n#### {icon} {entry['strategy'][:80]}…\n"
            f"- **Best result:** {entry['best_issues']} issues | **Tried:** {entry['count']}× | **Model:** {entry['model']}\n"
        )

    # Untried promising strategies (based on problem profile)
    untried_strategies = _generate_untried_strategies(problem_id, p, tried)

    doc = f"""# {problem_id.upper()}: Strategy Analysis

**Last updated:** {_now()}
**Strategies tried:** {len(tried)} distinct | **Total attempts:** {len(attempts)}

> This document maps the strategy space for {problem_id.upper()}.
> Strategies are classified as tried/promising/ruled-out.
> Cross-reference with [timeline.md](timeline.md) for attempt details.

---

## Recommended Strategy (from Problem Profile)

{p.get('strategy', '_No profile strategy available._')}

**Why this works:**
{p.get('candidate', '')}

---

## Strategy Space

### ✅/❌ Strategies Already Tried

{tried_block if tried_block else '_No attempts recorded yet._'}

---

### 🔍 Untried Promising Directions

{untried_strategies}

---

### 🚫 Strategies Likely to Fail

{_ruled_out_strategies(problem_id)}

---

## Quick Verification Checks

These computations can be done cheaply to test a strategy direction:

{_quick_checks(problem_id, p)}

---

## Agent Insights

*Populated automatically when critic/solver agents post mathematical analysis.*

{_load_agent_insights(repo_root, problem_id)}

---

*Updated after each agent run. Add manual insights by editing this file directly.*
"""
    out.write_text(doc, encoding="utf-8")
    return out


def _generate_untried_strategies(problem_id: str, p: dict, tried: dict) -> str:
    all_strategies = {
        "q1": [
            "**Cameron-Martin + Nelson hypercontractivity (standard):** The profile strategy. Bound the Wick polynomial density via $L^p$ estimates.",
            "**Borell-Cirelson inequality approach:** Use concentration of measure on Wiener space to bound the density directly.",
            "**Stochastic quantization approach:** Show quasi-invariance via the SDE for $\\Phi^4_3$ dynamics and Girsanov's theorem.",
        ],
        "q2": [
            "**Kirillov model + conductor translate (standard):** The profile strategy. Construct $W$ with compact support near $u_Q$.",
            "**Multiplicity-one approach:** Use the uniqueness of the Whittaker model to reduce to a specific matrix coefficient calculation.",
            "**Zeta integral factorization:** Factor the local integral into simpler zeta integrals and show not all vanish.",
        ],
        "q3": [
            "**Adjacent transposition Metropolis chain (standard):** The profile strategy. Compute local weight ratios from the branching rule.",
            "**Interacting particle system approach:** Model the chain as a multi-particle system and use generating function methods.",
            "**RSK-type bijection:** Construct an explicit bijection that transports the Macdonald measure to a product measure.",
        ],
        "q4": [
            "**Finite-free heat flow + differential identity (standard):** The profile strategy.",
            "**Interlacing polynomial approach:** Use the MSS interlacing families directly to bound $\\Phi_n$ under convolution.",
            "**Moment comparison:** Compare moments of the root distribution before/after convolution to bound Fisher information.",
        ],
        "q5": [
            "**Localizing subcategory approach (standard):** The profile strategy. Define via generators and check fixed-point criterion.",
            "**Postnikov tower comparison:** Compare $\\mathcal{O}$-slice filtration to Postnikov tower; extract connectivity statements.",
            "**Mackey decomposition:** Use Mackey's restriction formula for geometric fixed points to check the filtration axioms.",
        ],
        "q6": [
            "**Spectral vertex paving + averaging (standard/profile):** Apply MSS paving theorem, take largest part.",
            "**Direct greedy construction:** Build $S$ greedily by adding vertices that maintain $\\varepsilon$-lightness; bound size by expansion arguments.",
            "**Probabilistic method:** Choose $S$ randomly (e.g., each vertex independently with probability $p$) and show $\\varepsilon$-lightness in expectation.",
            "**Expander mixing lemma approach:** For regular graphs, use the spectral gap to directly bound the induced subgraph Laplacian.",
            "**Cheeger inequality reduction:** Relate $\\varepsilon$-light sets to balanced cuts; use Cheeger's inequality to find large light set.",
        ],
        "q7": [
            "**Smith theory obstruction (standard):** Show the free $\\mathbb{Z}/2$-action on $\\tilde{M}$ contradicts Smith theory for acyclic spaces.",
            "**Euler characteristic parity:** For aspherical manifolds with 2-torsion $\\gamma\\in\\pi_1$, compute $\\chi(M/\\gamma)$ and derive a contradiction.",
            "**L²-cohomology approach:** Use Atiyah's $L^2$ index theorem to derive a contradiction from the torsion element.",
        ],
        "q8": [
            "**Maslov index obstruction (standard):** Compute Maslov index of Legendrian link; show it prevents exact Lagrangian filling.",
            "**Legendrian contact homology (DGA) approach:** Compute the Chekanov-Eliashberg DGA of the link; show it has no augmentation.",
            "**Symplectic capacity obstruction:** Show the capacity of the region near the four-face vertex obstructs a smooth Lagrangian.",
        ],
        "q9": [
            "**Toric binomial generators (standard):** $2\\times 2$ minors of flattenings cut out the scaling locus.",
            "**Gröbner basis approach:** Compute a Gröbner basis of the toric ideal; verify it generates the full ideal.",
            "**Geometric approach:** Show the image of $(A,B,C,D)\\mapsto Q$ is a toric variety and identify its equations from the structure of the group action.",
        ],
        "q10": [
            "**PCG with Kronecker preconditioner (standard):** The profile strategy. Implicit matrix-vector products + $(Z^TZ+\\lambda I)\\otimes K$ preconditioner.",
            "**Randomized preconditioner:** Use a random sketch to approximate the observed covariance; precompute a low-rank preconditioner.",
            "**Direct solve via block structure:** Exploit block-diagonal structure of the observed design to solve each block independently.",
        ],
    }
    strategies = all_strategies.get(problem_id, [])
    tried_keys = set(k[:60] for k in tried.keys())
    untried = [s for s in strategies if s[:60] not in tried_keys and "standard" not in s.lower()]
    if not untried:
        return "_All identified strategies have been attempted or are covered by the standard approach._"
    return "\n".join(f"{i+1}. {s}" for i, s in enumerate(untried))


def _ruled_out_strategies(problem_id: str) -> str:
    ruled_out = {
        "q1": "- **Direct functional analytic argument without renormalization:** $\\Phi^4_3$ is not a function, so classical quasi-invariance arguments fail without Wick renormalization.",
        "q2": "- **Reducing to the unramified case:** Ramified representations require different vector constructions; the spherical vector does not work.",
        "q3": "- **Computing $F^*_\\mu$ directly:** The polynomials have no closed product formula; their direct evaluation is intractable.",
        "q4": "- **Classical Fisher information inequality:** The classical inequality uses convolution; finite free convolution has different properties.",
        "q5": "- **Using the classical HHR slice filtration without modification:** The HHR filtration is not compatible with the $N_\\infty$ algebra structure when $\\mathcal{O}\\neq E_\\infty$.",
        "q6": "- **Purely combinatorial arguments without spectral theory:** The $\\varepsilon$-light condition is inherently spectral; combinatorial bounds alone do not achieve a universal constant.",
        "q7": "- **Direct construction of a manifold with 2-torsion fundamental group:** The argument is an obstruction proof; no such manifold exists.",
        "q8": "- **$h$-principle arguments:** The $h$-principle for Lagrangians applies to open conditions, not to the existence of fillings with prescribed boundary.",
        "q9": "- **Linear algebra / rank conditions alone:** The determinantal structure is nonlinear; rank conditions on $Q$ alone do not characterize the image.",
        "q10": "- **Explicit formation of $Z\\otimes K$:** This matrix is $nr\\times nr$ and cannot be stored for large $n,r$.",
    }
    return ruled_out.get(problem_id, "_No ruled-out strategies identified yet._")


def _quick_checks(problem_id: str, p: dict) -> str:
    checks = {
        "q1": "```python\n# Check Cameron-Martin space inclusion: ψ must be in H¹(T³)\nimport numpy as np\n# For a smooth test function ψ, verify ∫|∇ψ|² < ∞\n# This is always true for smooth ψ\n```",
        "q6": "```python\n# Verify ε-lightness: check L_S ⪯ ε*L (all eigenvalues of ε*L - L_S ≥ 0)\nimport numpy as np\ndef is_eps_light(L, S, eps):\n    L_S = L[np.ix_(S,S)]  # induced Laplacian (restricted to S×S, zero elsewhere)\n    L_S_full = np.zeros_like(L)\n    L_S_full[np.ix_(S,S)] = L_S\n    diff = eps * L - L_S_full\n    return np.all(np.linalg.eigvalsh(diff) >= -1e-10)\n# Test on K_4\nn = 4; L = n*np.eye(n) - np.ones((n,n))\nS = [0,1]  # try a 2-vertex subset\nprint(is_eps_light(L, S, 0.5))  # should be True\n```",
        "q4": "```python\n# Check real-rootedness under finite-free convolution\nimport numpy as np\nfrom numpy.polynomial import polynomial as P\n# p = x² - 1 (roots ±1), q = x² - 4 (roots ±2)\n# p ⊞₂ q should be real-rooted\n# Coefficients of p⊞₂q: E[p(U)q(V)] for Haar-random U,V\n# For degree 2: (p⊞q)(x) = x² - (e₁(p)e₁(q)/2 + e₂(p) + e₂(q))\n```",
        "q10": "```python\n# Verify SPD of normal equation operator\nimport numpy as np\ndef normal_eq_operator(K, Z, Omega, lam):\n    n, r = K.shape[0], Z.shape[1]\n    # Build A = Σ_{(i,j)∈Ω} (K e_i)(Z_j)^T ⊗ (K e_i)(Z_j)^T + λ(I⊗K)\n    # For small n,r: build explicitly to verify SPD\n    nr = n * r\n    A = lam * np.kron(np.eye(r), K)\n    for i, j in Omega:\n        v = np.zeros(nr); v[j*n+i] = 1  # vec(e_i e_j^T)\n        kv = np.kron(Z[j:j+1,:].T, K[:,i:i+1])  # (Z⊗K) column\n        A += kv @ kv.T\n    return A\n```",
    }
    return checks.get(problem_id, "_No specific quick checks defined yet. Add Python verification scripts here._")


def _load_agent_insights(repo_root: Path, problem_id: str) -> str:
    """Pull recent substantive agent comments from the issue tracker."""
    issues = _load_issues(repo_root, problem_id)
    insights = []
    for issue in issues:
        for c in issue.get("comments", []):
            author = c.get("author", "")
            if author in ("critic-agent", "solver-agent", "verifier-agent") and len(c.get("body", "")) > 100:
                ts = c.get("created_at", "")[:10]
                body = c.get("body", "").strip()[:500]
                insights.append(f"**[{author} @ {ts}]** — Issue [{issue['id']}]\n\n> {body}\n")
    return "\n".join(insights) if insights else "_No agent insights recorded yet. Run the issue cycle to populate this section._"


# ── Master update ─────────────────────────────────────────────────────────────

def update_question_document(
    repo_root: Path,
    problem_id: str,
    reasoning_trace: str = "",
    model_used: str = "",
    run_outcome: str = "",
) -> dict[str, Path]:
    """Update all four documents for a question. Returns dict of written paths."""
    paths = {}
    # overview.md: only write if it doesn't exist yet (static reference)
    ov = question_dir(repo_root, problem_id) / "overview.md"
    if not ov.is_file():
        paths["overview"] = write_overview(repo_root, problem_id)
    else:
        paths["overview"] = ov
    paths["timeline"] = update_timeline(repo_root, problem_id)
    paths["progress"] = update_progress(repo_root, problem_id, reasoning_trace, model_used, run_outcome)
    paths["strategies"] = update_strategies(repo_root, problem_id)
    return paths


def seed_all_question_documents(repo_root: Path) -> dict[str, list[Path]]:
    """Generate all four documents for all 10 problems."""
    result = {}
    for i in range(1, 11):
        pid = f"q{i}"
        written = []
        written.append(write_overview(repo_root, pid))
        written.append(update_timeline(repo_root, pid))
        written.append(update_progress(repo_root, pid))
        written.append(update_strategies(repo_root, pid))
        result[pid] = written
    return result


# ── discussions/index.md ──────────────────────────────────────────────────────

def update_discussion_index(repo_root: Path) -> Path:
    now = _now()

    # Per-problem status summary
    status_rows = []
    for i in range(1, 11):
        pid = f"q{i}"
        attempts = _load_attempts(repo_root, pid)
        status = _status_emoji(attempts)
        best = min((a.get("issue_count", 99) for a in attempts), default=None)
        models = list({a.get("model", "skeleton") for a in attempts})
        status_rows.append(
            f"| [{pid}](questions/{pid}/progress.md) | {status} | {len(attempts)} | "
            f"{'%d issues' % best if best is not None else 'no data'} | {', '.join(models[:2])} |"
        )

    doc = f"""# Research Math Agent — Document Hub

**Last updated:** {now}

This is the master index for all ResearchMathAgent documents.
Click any problem to see its full documentation hierarchy.

---

## Problem Status Dashboard

| Problem | Status | Attempts | Best Result | Models Used |
|---------|--------|----------|-------------|-------------|
{chr(10).join(status_rows)}

---

## Document Hierarchy

Each problem `qN` has four documents under `documents/questions/qN/`:

| File | Purpose | Update Frequency |
|------|---------|-----------------|
| [`overview.md`] | Static background: problem statement, definitions, key theorems, why it's hard | Once (manual updates) |
| [`timeline.md`] | Chronological log of every proof attempt with outcome and strategy | After every `rma solve` run |
| [`progress.md`] | Live status: what's established, what's open, latest reasoning trace | After every run |
| [`strategies.md`] | Strategy space: tried/untried/ruled-out approaches, quick checks, agent insights | After every run |

---

## Thematic Clusters

### Cluster A — Spectral & Polynomial Methods
**Problems:** [q4](questions/q4/overview.md), [q6](questions/q6/overview.md), [q9](questions/q9/overview.md)

All three problems involve understanding spectral decompositions or polynomial structure under a natural operation:
- **q4**: Polynomials with real roots, Fisher information under finite free convolution ⊞ₙ
- **q6**: Graph Laplacians, spectral paving, ε-light subsets
- **q9**: Determinantal polynomials, algebraic identifiability via toric ideals

**Shared tool:** The Marcus-Spielman-Srivastava theorem (= Kadison-Singer) underlies both q4 and q6.

---

### Cluster B — Topology & Obstruction Theory
**Problems:** [q5](questions/q5/overview.md), [q7](questions/q7/overview.md), [q8](questions/q8/overview.md)

All three prove nonexistence via a cohomological or fixed-point obstruction:
- **q5**: N∞ operad structure constrains the slice filtration via transfer systems
- **q7**: 2-torsion deck transformation contradicts Smith theory for acyclic spaces
- **q8**: Four-face vertex Maslov index prevents an exact Lagrangian filling

**Common pattern:** Assume the desired object exists → compute an invariant → derive contradiction.

---

### Cluster C — Analysis & Measure Theory
**Problems:** [q1](questions/q1/overview.md), [q2](questions/q2/overview.md), [q3](questions/q3/overview.md)

All three involve highly structured mathematical objects where a precise local calculation unlocks the global result:
- **q1**: Φ⁴₃ Gibbs measure, Cameron-Martin theorem, Wick renormalization
- **q2**: Whittaker models, Rankin-Selberg pairing, conductor translate
- **q3**: Interpolation Macdonald polynomials, branching rule, Markov chains

---

### Cluster D — Computational & Constructive
**Problems:** [q9](questions/q9/overview.md), [q10](questions/q10/overview.md)

Both require explicit algorithmic constructions, not existence proofs:
- **q9**: Find bounded-degree polynomial equations for the determinantal locus
- **q10**: Give a PCG algorithm with per-iteration cost avoiding O(N) and O(M)

---

## Recurring Proof Patterns

| Pattern | Problems | Description |
|---------|---------|-------------|
| Averaging / Pigeonhole | q6, q3 | Partition space, bound each part, take the best |
| Local model reduction | q8, q2, q1 | Reduce global question to a local computation |
| Heat flow / deformation | q4, q1 | Track a quantity along a natural continuous flow |
| Fixed-point obstruction | q7, q8, q5 | Assume existence → compute invariant → contradict |
| Whittaker / spectral test vector | q2 | Construct an explicit test vector for nonvanishing |

---

## Discussion Threads

### Thread 1: Is c = 1/42 or c = 1/2 tight for q6?
The current proof gives c = 1/(3C) ≈ 1/54 via MSS with C ≤ 18.
Spielman conjectures c = 1/2, achieved by the complete graph Kₙ.
**Open:** Can the RMA agent find a sharper paving argument?

### Thread 2: What is the mixing time of the Macdonald chain? (q3)
Williams' chain is well-defined and reversible but its spectral gap is unknown.
**Open:** Is the mixing time polynomial in n?

### Thread 3: Can q4 and q6 be connected directly?
Both use the MSS theorem as a black box. Is there a direct proof of q6
that goes through finite-free probability (q4)?

---

## Recent Activity

*Populated automatically by the daily runner. See individual problem timelines for details.*

---

*This index is auto-maintained by `webapp/rich_documents.py`.*
*To add a discussion thread, edit this file or post an issue in `webapp/issues/first_proof_1/`.*
"""
    out = discussions_dir(repo_root) / "index.md"
    out.write_text(doc, encoding="utf-8")
    return out


# ── Top-level README ──────────────────────────────────────────────────────────

def write_documents_readme(repo_root: Path) -> Path:
    doc = f"""# ResearchMathAgent — Documents

**Generated:** {_now()}

This directory contains all research documentation for the First Proof benchmark.

## Quick Navigation

- **[discussions/index.md](discussions/index.md)** — Master hub: status dashboard, thematic clusters, discussion threads
- **questions/qN/** — Per-question documentation (4 files each):
  - `overview.md` — Problem statement, background, definitions, key theorems
  - `timeline.md` — Every attempt, chronological, with outcomes
  - `progress.md` — Live status, best result, open gaps, next steps
  - `strategies.md` — Strategy space, quick checks, agent insights
- **strategy_memory.jsonl** — Raw attempt log (feeds all documents above)

## Problems

| ID | Title | Status |
|----|-------|--------|
{chr(10).join(f'| [q{i}](questions/q{i}/overview.md) | See overview.md | [progress](questions/q{i}/progress.md) |' for i in range(1,11))}

## How Documents Are Updated

- After every `rma solve` run: `timeline.md`, `progress.md`, `strategies.md` are refreshed
- After every critic/solver agent run: `strategies.md` receives agent insights; `progress.md` gets reasoning traces
- `overview.md` is static — update it manually as understanding of the problem deepens
- `discussions/index.md` is refreshed after every daily run

## Adding Manual Notes

Edit any `.md` file directly. Agent-generated content is appended in clearly marked sections.
Manual notes above the `---` dividers are preserved across auto-updates.
"""
    out = repo_root / "documents" / "README.md"
    out.write_text(doc, encoding="utf-8")
    return out
