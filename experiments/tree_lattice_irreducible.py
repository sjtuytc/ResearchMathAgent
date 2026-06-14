#!/usr/bin/env python3
"""
Brute-force test of an irreducibility claim for tree Gram lattices.

Tree T on V={0..n-1}, integer weights w(u)>=1.
M[u][u]=w(u); M[u][x]=-1 if (u,x) edge; else 0.  (path-graph / tree Cartan-like form)
L(T)=Z^n with form x.y = x^T M y. Require M positive definite.

e_u reducible  <=>  exists nonzero a,b in Z^n, a+b=e_u, a.b = a^T M b >= 0.
With b=e_u-a: a.b = a.e_u - a.a = (Me_u)·a - a^T M a = (column u of M)·a - |a|^2.
Reducible iff exists nonzero a != e_u with |a|^2 <= a.e_u and (e_u-a) nonzero.
Since |a|^2>=1, need a.e_u>=1, and a.e_u = sum_x M[x][u] a[x]... careful: a.e_u = a^T M e_u = (M a)[u]?
M symmetric so a^T M e_u = e_u^T M a = (M a)[u]. We'll just compute a^T M e_u directly.

Search: enumerate all lattice vectors a with 1 <= |a|^2 <= w(u)-1 (since |a|^2+|b|^2<=w(u),
both>=1). Bounding box from lambda_min.
"""
import itertools
import numpy as np

def build_M(n, edges, w):
    M = np.zeros((n, n), dtype=np.int64)
    for u in range(n):
        M[u, u] = w[u]
    for (a, b) in edges:
        M[a, b] = -1
        M[b, a] = -1
    return M

def is_pd(M):
    try:
        np.linalg.cholesky(M.astype(np.float64))
        return True
    except np.linalg.LinAlgError:
        return False

def gen_trees(n):
    """All labeled trees on n vertices via Pruefer sequences (n>=2)."""
    if n == 1:
        yield []
        return
    if n == 2:
        yield [(0, 1)]
        return
    import heapq
    for seq in itertools.product(range(n), repeat=n - 2):
        # decode Pruefer sequence into edge list
        degc = [1] * n
        for x in seq:
            degc[x] += 1
        heap = [i for i in range(n) if degc[i] == 1]
        heapq.heapify(heap)
        edges = []
        for x in seq:
            leaf = heapq.heappop(heap)
            edges.append(tuple(sorted((leaf, x))))
            degc[leaf] -= 1
            degc[x] -= 1
            if degc[x] == 1:
                heapq.heappush(heap, x)
        rem = [i for i in range(n) if degc[i] == 1]
        edges.append(tuple(sorted(rem[:2])))
        yield edges

def short_vectors(M, max_norm, lam_min):
    """Yield all integer vectors a with 1 <= a^T M a <= max_norm via bounded box + recursion."""
    n = M.shape[0]
    if max_norm < 1:
        return
    B = int(np.ceil(np.sqrt(max_norm / max(lam_min, 1e-9)))) + 1
    # recursive enumeration with running quadratic form is overkill for small n; box filter
    rng = range(-B, B + 1)
    for a in itertools.product(rng, repeat=n):
        av = np.array(a, dtype=np.int64)
        if not av.any():
            continue
        q = int(av @ M @ av)
        if 1 <= q <= max_norm:
            yield av, q

def is_reducible(M, u, lam_min):
    """e_u reducible? search a with 1<=|a|^2<=w(u)-1, b=e_u-a nonzero, a.b>=0."""
    n = M.shape[0]
    wu = int(M[u, u])
    e = np.zeros(n, dtype=np.int64); e[u] = 1
    for av, q in short_vectors(M, wu - 1, lam_min):
        b = e - av
        if not b.any():
            continue
        adotb = int(av @ M @ b)
        if adotb >= 0:
            return True, (av.copy(), b.copy(), adotb)
    return False, None

def degrees(n, edges):
    d = [0] * n
    for (a, b) in edges:
        d[a] += 1; d[b] += 1
    return d

def run():
    weights_choices = [1, 2, 3, 4]
    total_valid = 0
    trees_with_irr = 0
    counterexamples = []
    records = []  # per (tree, vertex)
    # pattern counters
    w1_irr = w1_red = 0
    leaf_irr = leaf_red = 0
    v_unique_irr = 0  # deficient vertex is unique irreducible
    # w(u) vs d(u) class -> (irr,red)
    classcount = {}  # key: 'lt','eq','gt'
    # weight-2 orthogonal-split equivalence
    w2_match = w2_mismatch = 0

    for n in range(2, 7):
        for edges in gen_trees(n):
            d = degrees(n, edges)
            for w in itertools.product(weights_choices, repeat=n):
                # exactly one vertex with w<d
                deficient = [u for u in range(n) if w[u] < d[u]]
                if len(deficient) != 1:
                    continue
                M = build_M(n, edges, w)
                if not is_pd(M):
                    continue
                lam_min = float(np.linalg.eigvalsh(M.astype(np.float64)).min())
                total_valid += 1
                v = deficient[0]
                irr_vertices = []
                for u in range(n):
                    red, _ = is_reducible(M, u, lam_min)
                    if not red:
                        irr_vertices.append(u)
                    # patterns
                    cls = 'lt' if w[u] < d[u] else ('eq' if w[u] == d[u] else 'gt')
                    c = classcount.setdefault(cls, [0, 0])
                    if red: c[1] += 1
                    else: c[0] += 1
                    if w[u] == 1:
                        if red: w1_red += 1
                        else: w1_irr += 1
                    if d[u] == 1:
                        if red: leaf_red += 1
                        else: leaf_irr += 1
                    # weight-2 orthogonal-split test
                    if w[u] == 2:
                        ortho = w2_has_ortho_split(M, u, lam_min)
                        if ortho == red:
                            w2_match += 1
                        else:
                            w2_mismatch += 1
                if irr_vertices:
                    trees_with_irr += 1
                else:
                    counterexamples.append((n, edges, w, d))
                if irr_vertices == [v]:
                    v_unique_irr += 1

    print("=" * 70)
    print(f"Valid PD trees with exactly one deficient vertex: {total_valid}")
    print(f"Trees with >=1 irreducible vertex (claim): {trees_with_irr}")
    print(f"Counterexamples (ALL vertices reducible): {len(counterexamples)}")
    for ce in counterexamples[:20]:
        print("  COUNTEREXAMPLE:", ce)
    print("-" * 70)
    print("PATTERNS")
    print(f"  weight-1 vertices: irreducible={w1_irr}, reducible={w1_red}")
    print(f"  leaf vertices (d=1): irreducible={leaf_irr}, reducible={leaf_red}")
    print(f"  trees where deficient v is the UNIQUE irreducible vertex: {v_unique_irr}")
    print("  class w(u) vs d(u)  ->  [irreducible, reducible]:")
    for k in ('lt', 'eq', 'gt'):
        if k in classcount:
            print(f"    {k}: {classcount[k]}")
    print("-" * 70)
    print(f"weight-2: reducible <=> orthogonal norm-1 split  match={w2_match} mismatch={w2_mismatch}")
    print("=" * 70)

def w2_has_ortho_split(M, u, lam_min):
    """For w(u)=2: does e_u = e+f with e,f norm-1 lattice vectors, e.f=0?"""
    n = M.shape[0]
    e = np.zeros(n, dtype=np.int64); e[u] = 1
    norm1 = [av for av, q in short_vectors(M, 1, lam_min) if q == 1]
    for ev in norm1:
        fv = e - ev
        if not fv.any():
            continue
        if int(fv @ M @ fv) == 1 and int(ev @ M @ fv) == 0:
            return True
    return False

if __name__ == "__main__":
    run()
