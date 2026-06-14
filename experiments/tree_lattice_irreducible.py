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
    """Yield all integer vectors a with 1 <= a^T M a <= max_norm.

    Rigorous Fincke-Pohst style enumeration via Cholesky M = R^T R (R upper).
    Then a^T M a = sum_i ( sum_{j>=i} R[i,j] a[j] )^2. Enumerate coords from last
    to first; at each level the partial sum of completed squares bounds choices,
    guaranteeing NO short vector is missed.
    """
    n = M.shape[0]
    if max_norm < 1:
        return
    R = np.linalg.cholesky(M.astype(np.float64)).T  # upper triangular, R^T R = M
    a = [0] * n
    EPS = 1e-9

    def rec(i, partial):
        # partial = sum over rows k>i of (sum_{j>=k} R[k,j] a[j])^2 already fixed
        # at row i: term = R[i,i]*a[i] + sum_{j>i} R[i,j]*a[j]
        rem = max_norm - partial
        if rem < -EPS:
            return
        if i < 0:
            av = np.array(a, dtype=np.int64)
            if av.any():
                q = int(av @ M @ av)  # exact integer norm, no float rounding
                if 1 <= q <= max_norm:
                    yield av, q
            return
        s = sum(R[i, j] * a[j] for j in range(i + 1, n))  # contribution of already-set higher coords
        rii = R[i, i]
        # |rii*ai + s| <= sqrt(rem); add slack so we never miss a valid coord
        half = np.sqrt(max(rem, 0.0) + 1e-6)
        lo = int(np.floor((-half - s) / rii - EPS))
        hi = int(np.ceil((half - s) / rii + EPS))
        for ai in range(lo, hi + 1):
            a[i] = ai
            term = rii * ai + s
            yield from rec(i - 1, partial + term * term)
        a[i] = 0

    yield from rec(n - 1, 0.0)

def short_vectors_fast(Mrows, R, max_norm):
    """Pure-Python version of short_vectors. Mrows: list of int rows. R: float upper Cholesky.
    Yields integer tuples a with 1 <= a^T M a <= max_norm."""
    n = len(Mrows)
    if max_norm < 1:
        return
    a = [0] * n
    EPS = 1e-9
    import math

    def quad(a):
        return sum(a[i] * Mrows[i][j] * a[j] for i in range(n) for j in range(n))

    def rec(i, partial):
        if max_norm - partial < -EPS:
            return
        if i < 0:
            if any(a):
                q = quad(a)
                if 1 <= q <= max_norm:
                    yield tuple(a)
            return
        s = 0.0
        Ri = R[i]
        for j in range(i + 1, n):
            s += Ri[j] * a[j]
        rii = Ri[i]
        half = math.sqrt(max(max_norm - partial, 0.0) + 1e-6)
        lo = int(math.floor((-half - s) / rii - EPS))
        hi = int(math.ceil((half - s) / rii + EPS))
        for ai in range(lo, hi + 1):
            a[i] = ai
            term = rii * ai + s
            yield from rec(i - 1, partial + term * term)
        a[i] = 0

    yield from rec(n - 1, 0.0)


def is_reducible_fast(Mrows, R, u):
    """e_u reducible? Pure-python. Mrows int rows, R float upper Cholesky."""
    n = len(Mrows)
    wu = Mrows[u][u]
    for av in short_vectors_fast(Mrows, R, wu - 1):
        # b = e_u - a; require b nonzero
        b = [(-av[k]) for k in range(n)]
        b[u] += 1
        if not any(b):
            continue
        # a.b = a^T M b
        adotb = sum(av[i] * Mrows[i][j] * b[j] for i in range(n) for j in range(n))
        if adotb >= 0:
            return True
    return False


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
    # candidate sufficient-condition tallies: name -> [num_irreducible, num_reducible]
    cond_tally = {k: [0, 0] for k in ('w<=d', 'w==1', 'leaf&w==1', 'w<d', 'w==d')}

    import random
    random.seed(12345)
    # n=2..5 exhaustive; n=6 random sample of weight combos per tree (tractable, still covers n=6)
    SAMPLE_N6 = 40  # weight combos sampled per n=6 tree

    def configs(n, edges, d):
        if n <= 5:
            yield from itertools.product(weights_choices, repeat=n)
        else:
            for _ in range(SAMPLE_N6):
                yield tuple(random.choice(weights_choices) for _ in range(n))

    for n in range(2, 7):
        for edges in gen_trees(n):
            d = degrees(n, edges)
            for w in configs(n, edges, d):
                # exactly one vertex with w<d
                deficient = [u for u in range(n) if w[u] < d[u]]
                if len(deficient) != 1:
                    continue
                M = build_M(n, edges, w)
                try:
                    Rnp = np.linalg.cholesky(M.astype(np.float64)).T
                except np.linalg.LinAlgError:
                    continue
                R = [[float(Rnp[i, j]) for j in range(n)] for i in range(n)]
                Mrows = [[int(M[i, j]) for j in range(n)] for i in range(n)]
                total_valid += 1
                v = deficient[0]
                irr_vertices = []
                red_status = {}
                for u in range(n):
                    red = is_reducible_fast(Mrows, R, u)
                    red_status[u] = red
                    if not red:
                        irr_vertices.append(u)
                    # candidate sufficient conditions for IRREDUCIBILITY
                    # C1: w(u) <= d(u)
                    if w[u] <= d[u]:
                        cond_tally['w<=d'][0 if not red else 1] += 1
                    # C2: w(u) == 1
                    if w[u] == 1:
                        cond_tally['w==1'][0 if not red else 1] += 1
                    # C3: leaf with w(u)==1
                    if d[u] == 1 and w[u] == 1:
                        cond_tally['leaf&w==1'][0 if not red else 1] += 1
                    # C4: w(u) < d(u) (the deficient vertex)
                    if w[u] < d[u]:
                        cond_tally['w<d'][0 if not red else 1] += 1
                    # C5: w(u) == d(u)
                    if w[u] == d[u]:
                        cond_tally['w==d'][0 if not red else 1] += 1
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
                        ortho = w2_has_ortho_split_fast(Mrows, R, u)
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
    print("CANDIDATE SUFFICIENT CONDITIONS for IRREDUCIBILITY  [irreducible, reducible]:")
    print("  (if reducible count == 0, the condition GUARANTEES irreducibility)")
    for k, (irr, red) in cond_tally.items():
        verdict = "SUFFICIENT (never reducible)" if red == 0 and irr > 0 else "not sufficient"
        print(f"    {k:12s}: irr={irr:7d} red={red:7d}  -> {verdict}")
    print("-" * 70)
    print(f"weight-2: reducible <=> orthogonal norm-1 split  match={w2_match} mismatch={w2_mismatch}")
    print("=" * 70)

def w2_has_ortho_split_fast(Mrows, R, u):
    """For w(u)=2: does e_u = e+f with e,f norm-1 lattice vectors, e.f=0? Pure python."""
    n = len(Mrows)
    def dot(x, y):
        return sum(x[i] * Mrows[i][j] * y[j] for i in range(n) for j in range(n))
    norm1 = [list(av) for av in short_vectors_fast(Mrows, R, 1)]  # all have q==1 since max_norm=1
    for ev in norm1:
        fv = [-ev[k] for k in range(n)]
        fv[u] += 1
        if not any(fv):
            continue
        if dot(fv, fv) == 1 and dot(ev, fv) == 0:
            return True
    return False


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
