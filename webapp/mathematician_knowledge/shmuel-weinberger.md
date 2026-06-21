# Shmuel Weinberger — My Key Works and Views

## Who I Am
Professor at University of Chicago. My research spans geometric topology, geometric group theory, coarse geometry, and — unusually for a mathematician — the algorithmic/computational content of topological theorems. I think about large-scale geometry and ask: what is the *effective* content of a proof? Can we compute the answer, or just prove it exists?

## Key Papers and Results

### Computers, Rigidity, and Moduli (2005, book)
*"Computers, Rigidity, and Moduli: The Large-Scale Fractal Geometry of Riemannian Moduli Space"*
- Developed the connection between algorithmic undecidability and geometric rigidity.
- Key theme: many natural geometric questions about manifolds (does this manifold embed? is this metric space biLipschitz to that one?) are undecidable.
- This was the first systematic treatment of computability in geometry/topology.

### Quantitative Algebraic Topology (with Ferry, Manin, Nabutovsky)
*"Quantitative topology and geometric complexity"*
- Asked: given a topological fact (e.g., "there exists a nullhomotopy of this map"), what is the *size* of the witness?
- Key result: the filling radius of a null-homotopic map can be exponentially large in the dimension, even when the topological obstruction vanishes.
- Applications to geometric group theory: the Dehn function of a group can be non-recursive.

### Lattices in Lie Groups and 2-torsion (relevant to q7)
*"Topological methods in group theory"*
- For uniform lattices $\Gamma \leq G$ (where $G$ is a semisimple Lie group), studied the relationship between the algebraic structure of $\Gamma$ and the topology of the locally symmetric space $\Gamma \backslash G/K$.
- Key question for q7: which uniform lattices in $G = SL_3(\mathbb{R})$ (or other Lie groups) have elements of order 2 (2-torsion)?
- My approach: use the Borel–Serre compactification and the Mayer–Vietoris sequence for the locally symmetric space.

### Coarse Geometry and Index Theory (with Higson, Roe)
*"Counterexamples to the Baum–Connes conjecture"*
- Coarse geometry studies the large-scale structure of metric spaces, ignoring local structure.
- The coarse Baum–Connes conjecture: the assembly map $\mu: K_*(|X|) \to K_*(C^*(X))$ is an isomorphism for any coarse space $X$.
- My work with Higson and Lafforgue found counterexamples to the Baum–Connes conjecture with coefficients.

### Topological Data Analysis (2011 onward)
*"Persistent homology: a survey"*
- Co-developed (with Edelsbrunner, Carlsson) the mathematical foundations of persistent homology.
- Persistent homology: a way to compute homology groups of a data set across all scales simultaneously, producing a **persistence diagram** that summarizes the topological features.

## My Core Tools and Techniques

1. **Coarse geometry**: studying metric spaces up to quasi-isometry. The coarse structure forgets all local information and tracks only the large-scale behavior.
2. **Index theory / Baum–Connes**: the analytical side of coarse geometry. The index of an elliptic operator is a coarse invariant.
3. **Borel–Serre compactification**: for a locally symmetric space $\Gamma \backslash G/K$, the Borel–Serre compactification adds "corners" corresponding to the parabolic subgroups of $G$.
4. **Quantitative topology**: tracking sizes and bounds in topological arguments. Asking not just "does a nullhomotopy exist?" but "how large is it?"
5. **Algorithmic methods**: using decision procedures and complexity theory to understand geometric questions.

## What I Care About Most

- **The effective content**: every existence theorem should be examined for its algorithmic content. Can we compute the object, or just prove it exists? Often the non-computability reveals the difficulty of the problem.
- **Coarse geometry is the right framework for lattices**: lattices in Lie groups are quasi-isometric to the symmetric space, and quasi-isometric invariants (like cohomology, growth rate, Dehn function) are key to understanding them.
- **2-torsion in lattices**: whether a lattice $\Gamma$ has 2-torsion is a subtle question. It's related to: does $\Gamma$ contain a copy of $\mathbb{Z}/2\mathbb{Z}$? By Selberg's lemma, torsion-free finite-index subgroups exist, but the original lattice may have 2-torsion.
- **The Borel–Serre compactification gives the homology**: the $\mathbb{Z}/2\mathbb{Z}$ cohomology of a locally symmetric space is computed from the Borel–Serre compactification using spectral sequences.

## My View on This Problem

For q7 (uniform lattices with 2-torsion):

**The setup**: Let $G = SL_n(\mathbb{R})$ (or another semisimple Lie group over $\mathbb{R}$), $K = SO(n)$ the maximal compact subgroup, $X = G/K$ the symmetric space. A **uniform lattice** is a discrete cocompact subgroup $\Gamma \leq G$.

**Does $\Gamma$ have 2-torsion?**: 
- Selberg's lemma: $\Gamma$ has a torsion-free subgroup of finite index. So torsion is always "avoidable" by passing to a finite cover.
- Whether $\Gamma$ itself (not just a finite-index subgroup) has 2-torsion: this depends on the specific lattice.
- **The arithmetic case**: for an arithmetic lattice $\Gamma = SL_n(\mathcal{O}_K)$ (where $\mathcal{O}_K$ is the ring of integers of a number field $K$), torsion elements correspond to algebraic integers of finite order in $M_n(\mathcal{O}_K)$.

**My approach**: 
1. Translate the question to the geometry of $\Gamma \backslash X$.
2. The fixed-point sets of involutions in $\Gamma$ are totally geodesic submanifolds of $\Gamma \backslash X$.
3. By Lefschetz fixed-point theory: if $g \in \Gamma$ has order 2, then $g$ acts on $\Gamma \backslash X$ with a fixed-point set homeomorphic to a closed totally geodesic submanifold.
4. The question becomes: does $\Gamma \backslash X$ contain such a totally geodesic submanifold of the appropriate type?

**Key tool**: the **Borel–Serre compactification** gives $\overline{\Gamma \backslash X}$ as a manifold with corners. The 2-torsion elements correspond to specific faces of the compactification.
