"""
Brute-force test of an irreducibility claim for PD weighted-tree lattices.

Lattice L(T) = Z^n with Gram matrix M:
    M[u][u] = w(u),  M[u][x] = -1 if (u,x) edge else 0.
A basis vertex e_u is REDUCIBLE if exist nonzero a,b in Z^n, a+b=e_u, a.b = a^T M b >= 0.
Otherwise IRREDUCIBLE.

Reduction test: b = e_u - a. a.b = a^T M e_u - a^T M a >= 0  <=>  |a|^2 <= a.e_u
where |a|^2 = a^T M a in [1, w(u)-1] for any nonzero a giving a valid split.
So enumerate all lattice vectors a with 1 <= a^T M a <= w(u)-1 and check a^T M a <= (M a)[u].

CLAIM: For every PD weighted tree with EXACTLY ONE vertex v having w(v) < deg(v),
at least one vertex is irreducible.
"""
import itertools
import numpy as np

WEIGHTS = [1, 2, 3, 4]


def all_trees(n):
    """Yield edge-lists of all labeled trees on n vertices via Prufer sequences."""
    if n == 1:
        yield []
        return
    if n == 2:
        yield [(0, 1)]
        return
    for seq in itertools.product(range(n), repeat=n - 2):
        # Prufer decode
        degree = [1] * n
        for x in seq:
            degree[x] += 1
        edges = []
        seq = list(seq)
        import heapq
        leaves = [i for i in range(n) if degree[i] == 1]
        heapq.heapify(leaves)
        s = list(seq)
        for x in s:
            leaf = heapq.heappop(leaves)
            edges.append((leaf, x))
            degree[x] -= 1
            if degree[x] == 1:
                heapq.heappush(leaves, x)
        u = heapq.heappop(leaves)
        v = heapq.heappop(leaves)
        edges.append((u, v))
        yield [tuple(sorted(e)) for e in edges]


def gram(n, edges, w):
    M = np.zeros((n, n), dtype=np.int64)
    for i in range(n):
        M[i, i] = w[i]
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


def short_vectors(M, norm_cap):
    """Enumerate ALL nonzero integer vectors a with 1 <= a^T M a <= norm_cap.
    Recursive bounded search using the bounding box from lambda_min.
    Returns list of np.int64 arrays."""
    n = M.shape[0]
    if norm_cap < 1:
        return [], 0
    eig = np.linalg.eigvalsh(M.astype(np.float64))
    lam_min = float(eig[0])
    if lam_min <= 1e-9:
        lam_min = 1e-9
    B = int(np.ceil(np.sqrt(norm_cap / lam_min))) + 1
    out = []
    a = np.zeros(n, dtype=np.int64)

    def rec(i):
        if i == n:
            q = int(a @ M @ a)
            if 1 <= q <= norm_cap:
                out.append(a.copy())
            return
        for val in range(-B, B + 1):
            a[i] = val
            # cheap partial prune: skip if already huge using diagonal lower bound? keep simple+correct
            rec(i + 1)
        a[i] = 0

    rec(0)
    return out, B


def reducible(M, u):
    """Return (is_reducible, witness a or None). Brute force over short vectors."""
    wu = int(M[u, u])
    if wu <= 1:
        return False, None  # need |a|^2>=1 and |b|^2>=1 so |a|^2+|b|^2>=2 > w-... w=1 impossible
    cap = wu - 1
    sv, _ = short_vectors(M, cap)
    Mcol_u = M[:, u]  # (M a)[u] = a . (M e_u) ; a^T M e_u = a . M[:,u]
    for a in sv:
        q = int(a @ M @ a)          # |a|^2
        ae = int(a @ Mcol_u)        # a^T M e_u = a.e_u
        if q <= ae:                 # a.b = ae - q >= 0
            return True, a
    return False, None


def deg(n, edges):
    d = [0] * n
    for (x, y) in edges:
        d[x] += 1
        d[y] += 1
    return d


def main():
    valid = 0
    with_irred = 0
    counterexamples = []
    pat_w1_irred = [0, 0]      # weight-1 vertices: [irreducible, total]
    pat_leaf_small = [0, 0]    # leaf with w<=2: [irreducible, total]
    pat_v_is_unique_irred = 0  # deficient vertex is the ONLY irreducible one
    pat_wltd_irred = [0, 0]    # vertices with w<d (the deficient one): [irred,total]
    pat_wged_irred = [0, 0]    # vertices with w>=d : [irred,total]
    pat_wgtd_irred = [0, 0]    # vertices with w>d (strict): [irred,total]
    pat_weqd_irred = [0, 0]    # vertices with w==d : [irred,total]
    # weight-2 orthogonality test
    w2_total = 0
    w2_red_matches_ortho = 0
    w2_mismatch = []
    # candidate sufficient condition: leaf u with w(u) < ... check w(u)==1 OR (leaf and w(u) <= 2)?
    suff_fail = []  # cases where a proposed simple sufficient condition fails

    for n in range(2, 7):
        for edges in all_trees(n):
            d = deg(n, edges)
            for w in itertools.product(WEIGHTS, repeat=n):
                deficient = [i for i in range(n) if w[i] < d[i]]
                if len(deficient) != 1:
                    continue
                M = gram(n, edges, w)
                if not is_pd(M):
                    continue
                valid += 1
                v = deficient[0]
                irred_set = []
                red_flags = {}
                for u in range(n):
                    r, _ = reducible(M, u)
                    red_flags[u] = r
                    if not r:
                        irred_set.append(u)
                    # patterns
                    if w[u] == 1:
                        pat_w1_irred[1] += 1
                        if not r:
                            pat_w1_irred[0] += 1
                    if d[u] == 1 and w[u] <= 2:
                        pat_leaf_small[1] += 1
                        if not r:
                            pat_leaf_small[0] += 1
                    if w[u] < d[u]:
                        pat_wltd_irred[1] += 1
                        if not r:
                            pat_wltd_irred[0] += 1
                    if w[u] >= d[u]:
                        pat_wged_irred[1] += 1
                        if not r:
                            pat_wged_irred[0] += 1
                    if w[u] > d[u]:
                        pat_wgtd_irred[1] += 1
                        if not r:
                            pat_wgtd_irred[0] += 1
                    if w[u] == d[u]:
                        pat_weqd_irred[1] += 1
                        if not r:
                            pat_weqd_irred[0] += 1

                    # weight-2 orthogonality equivalence
                    if w[u] == 2:
                        w2_total += 1
                        ortho = w2_ortho_split_exists(M, u)
                        if r == ortho:
                            w2_red_matches_ortho += 1
                        else:
                            if len(w2_mismatch) < 20:
                                w2_mismatch.append((n, edges, w, u, r, ortho))

                if len(irred_set) == 0:
                    counterexamples.append((n, edges, w, v))
                else:
                    with_irred += 1
                    if irred_set == [v]:
                        pat_v_is_unique_irred += 1

                # proposed sufficient condition test: "any vertex u with w(u)==1 is irreducible"
                # and "any leaf u (deg 1) with w(u)>=1 that is not the deficient vertex... ".
                # Check: is there always an irreducible vertex among {u != v}? i.e. the non-deficient set.
                non_def_irred = [u for u in irred_set if u != v]
                if len(non_def_irred) == 0:
                    suff_fail.append((n, edges, w, v, irred_set))

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Valid PD trees with exactly one deficient vertex tested: {valid}")
    print(f"Trees with >=1 irreducible vertex: {with_irred}")
    print(f"COUNTEREXAMPLES (all vertices reducible): {len(counterexamples)}")
    for c in counterexamples[:10]:
        print("   !!! COUNTEREXAMPLE:", c)
    print()
    print("PATTERNS (irreducible / total):")
    print(f"  weight-1 vertices irreducible:          {pat_w1_irred[0]}/{pat_w1_irred[1]}")
    print(f"  leaf with w<=2 irreducible:             {pat_leaf_small[0]}/{pat_leaf_small[1]}")
    print(f"  deficient vertices (w<d) irreducible:   {pat_wltd_irred[0]}/{pat_wltd_irred[1]}")
    print(f"  vertices w>=d irreducible:              {pat_wged_irred[0]}/{pat_wged_irred[1]}")
    print(f"    of which w>d (strict) irreducible:    {pat_wgtd_irred[0]}/{pat_wgtd_irred[1]}")
    print(f"    of which w==d irreducible:            {pat_weqd_irred[0]}/{pat_weqd_irred[1]}")
    print(f"  trees where deficient v is UNIQUE irreducible vertex: {pat_v_is_unique_irred}")
    print()
    print("WEIGHT-2 ORTHOGONALITY EQUIVALENCE:")
    print(f"  reducible(u) == (exists orthogonal norm-1 split): {w2_red_matches_ortho}/{w2_total}")
    for m in w2_mismatch[:10]:
        print("   mismatch:", m)
    print()
    print("SUFFICIENT-CONDITION PROBE:")
    print(f"  trees where NO non-deficient vertex is irreducible: {len(suff_fail)}")
    for s in suff_fail[:10]:
        print("   ", s)


def w2_ortho_split_exists(M, u):
    """For w(u)=2: does e_u = e+f with e,f norm-1 (e^T M e = 1) lattice vectors,
    and e,f orthogonal (e^T M f = 0)? Note then automatically a.b=0>=0 -> reducible.
    Norm-1 vectors: enumerate short vectors of norm exactly 1."""
    n = M.shape[0]
    sv, _ = short_vectors(M, 1)  # norm exactly 1 (cap=1)
    norm1 = [a for a in sv if int(a @ M @ a) == 1]
    eu = np.zeros(n, dtype=np.int64); eu[u] = 1
    for e in norm1:
        f = eu - e
        if int(f @ M @ f) == 1 and int(e @ M @ f) == 0:
            return True
    return False


if __name__ == "__main__":
    main()
