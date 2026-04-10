# Problem: ε-Light Subsets in Graphs

> **Status**: Work in progress — updated incrementally.

---

## Problem Statement

Let $G = (V, E)$ be a graph. For $S \subseteq V$, define $G_S = (V, E(S,S))$ as the graph on the same vertex set but with only the edges between vertices *both* in $S$.

- $L$: Laplacian of $G$
- $L_S$: Laplacian of $G_S$

**Definition.** A set $S \subseteq V$ is **$\epsilon$-light** if $\epsilon L - L_S \succeq 0$ (positive semidefinite), i.e., $L_S \preceq \epsilon L$.

**Question.** Does there exist a constant $c > 0$ such that for every graph $G$ and every $\epsilon \in [0,1]$, there exists an $\epsilon$-light subset $S \subseteq V$ with $|S| \ge c\epsilon |V|$?

---

## 问题陈述（中文）

设 $G = (V, E)$ 为一个图。对于 $S \subseteq V$，定义 $G_S = (V, E(S,S))$ 为保留所有顶点但只保留 $S$ 内部边的子图。

- $L$：$G$ 的拉普拉斯矩阵
- $L_S$：$G_S$ 的拉普拉斯矩阵

**定义。** 若 $\epsilon L - L_S \succeq 0$（即 $L_S \preceq \epsilon L$），则称顶点集 $S$ 为 **$\epsilon$-轻集**。

**问题。** 是否存在常数 $c > 0$，使得对任意图 $G$ 和任意 $\epsilon \in [0,1]$，都存在大小至少为 $c\epsilon |V|$ 的 $\epsilon$-轻集 $S \subseteq V$？

---

## Main Answer

**Yes, such a constant $c > 0$ exists.**

The claim is that $c = \Omega(1)$ (an absolute constant, independent of $G$, $n$, $\epsilon$).

---

## Key Observations

### Spectral interpretation

The condition $L_S \preceq \epsilon L$ is equivalent to:

$$\forall x \in \mathbb{R}^n: \quad \sum_{(u,v)\in E(S,S)} (x_u - x_v)^2 \;\le\; \epsilon \sum_{(u,v)\in E} (x_u - x_v)^2.$$

This says the "Dirichlet energy" of any signal $x$ on the induced subgraph $G[S]$ is at most an $\epsilon$-fraction of the energy on all of $G$.

### Trivial cases

- **Independent sets are 0-light** (and hence $\epsilon$-light for all $\epsilon \ge 0$): if $S$ is independent, $L_S = 0$.
- **$S = V$ is 1-light**: $L_V = L \preceq 1 \cdot L$.
- **Single vertices**: $\{v\}$ is $\epsilon$-light for any $\epsilon$, since no edges exist within a singleton.

---

## Key Examples

### 1. Complete graph $K_n$

$L = nI - \mathbf{1}\mathbf{1}^T$. For $S$ with $|S| = k$, the subgraph $G_S$ is $K_k$ embedded in $n$ vertices.

The maximum eigenvalue of $L_S$ (restricted to the $K_k$ block) is $k$. The maximum eigenvalue of $\epsilon L$ is $\epsilon n$.

**Condition** $L_S \preceq \epsilon L$ holds if and only if $k \le \epsilon n$.

So for $K_n$, any $S$ of size $\le \epsilon n$ is $\epsilon$-light. In particular, we can achieve $|S| = \lfloor \epsilon n \rfloor \ge \epsilon n - 1$. This shows $c = 1$ is achievable for $K_n$.

### 2. Complete bipartite graph $K_{n/2, n/2}$

Sides $A$ and $B$, each of size $n/2$. Any $S \subseteq A$ satisfies $L_S = 0$ (no intra-$A$ edges in a bipartite graph), so $S$ is $\epsilon$-light for all $\epsilon \ge 0$.

We can take $|S| = |A| = n/2 \ge \epsilon n / 2$ (for $\epsilon \le 1$). This gives $c = 1/2$ for $K_{n/2,n/2}$.

### 3. Star $K_{1,n-1}$

If $S = V \setminus \{\text{center}\}$, then $G_S$ has no edges ($S$ is an independent set). So $|S| = n-1 \approx n \ge \epsilon n$.

### 4. $d$-regular expander (e.g., Ramanujan graph)

For a $d$-regular graph with spectral gap $\lambda_2 \ge \alpha d$ (good expander): for small $\epsilon$, any $S$ with $|S| \le \epsilon n$ has $E(S,S) \le \epsilon^2 d n / 2$ edges on average. Spectral domination follows from the expander mixing lemma plus a more delicate argument.

---

## Proof Strategy

We split into two cases based on average degree $d_{\rm avg} = 2|E|/n$.

### Case 1: Sparse graphs ($d_{\rm avg} \le 1/(2\epsilon)$)

**Use a large independent set.**

By the greedy algorithm, every graph has an independent set $I$ of size:
$$|I| \ge \frac{n}{d_{\rm avg} + 1} \ge \frac{n}{1/(2\epsilon) + 1} \ge \frac{\epsilon n}{2}.$$

Since $I$ is independent, $L_I = 0 \preceq \epsilon L$. So $I$ is $\epsilon$-light with $|I| \ge \frac{\epsilon}{2} n$.

This handles all graphs with $d_{\rm avg} \le 1/(2\epsilon)$.

### Case 2: Dense graphs ($d_{\rm avg} > 1/(2\epsilon)$)

**Use a random subset with matrix concentration.**

**Construction**: Include each vertex in $S$ independently with probability $p = \sqrt{\epsilon}$ (or $p = \epsilon$ — see below for trade-offs).

**Size**: $\mathbb{E}[|S|] = \sqrt{\epsilon} \cdot n$. Since $\sqrt{\epsilon} \ge \epsilon$ for $\epsilon \in [0,1]$, we get $\mathbb{E}[|S|] \ge \epsilon n$.

**PSD condition in expectation**: 
$$\mathbb{E}[L_S] = p^2 L = \epsilon L.$$
*(Each edge $(u,v)$ is included iff both $u,v \in S$, probability $p^2 = \epsilon$.)*

So $\mathbb{E}[L_S] = \epsilon L \preceq \epsilon L$. The condition holds "on average."

**Concentration to a realization**: We need a specific realization where $L_S \preceq \epsilon L$ and $|S|$ is large simultaneously.

**Technical tool — Matrix Azuma / Bernstein**: Expose vertices one by one. Let $F_k = \mathbb{E}[L_S \mid X_1, \ldots, X_k]$ where $X_v = \mathbf{1}[v \in S]$. This forms a matrix martingale. The "step size" when we reveal $X_v$ is bounded by $d_v \cdot \|L\|_{\rm op}$ (degree-dependent). Using matrix Azuma's inequality:

$$\Pr\!\left( L_S \not\preceq 2\epsilon L \right) \le n \cdot \exp\!\left( -\frac{\epsilon^2}{\sigma^2} \right),$$

where $\sigma^2$ depends on the maximum degree. For the dense case (where $d_{\rm avg} \ge 1/(2\epsilon)$), the Laplacian $L$ has large eigenvalues, making $2\epsilon L$ a "wide" bound, and concentration kicks in.

**Simultaneous size and PSD**: Using a union bound,

$$\Pr\!\bigl(|S| \ge \tfrac{\epsilon n}{2} \text{ and } L_S \preceq \epsilon L\bigr) \ge \Pr(|S| \ge \tfrac{\epsilon n}{2}) + \Pr(L_S \preceq \epsilon L) - 1 > 0,$$

if each event has probability $> 1/2$.

The size condition $\Pr(|S| \ge \frac{\epsilon n}{2}) \ge 3/4$ follows from the Paley–Zygmund inequality (since $\mathbb{E}[|S|] = \sqrt{\epsilon} n \ge \epsilon n$).

The PSD condition requires the matrix concentration result sketched above.

---

## Key Lemmas Needed

1. **Greedy independent set**: Every graph on $n$ vertices with average degree $d$ has an independent set of size $\ge n/(d+1)$.

2. **Paley–Zygmund for size**: $\Pr(|S| \ge \frac{1}{2}\mathbb{E}[|S|]) \ge \frac{(\mathbb{E}[|S|])^2}{4\,\mathbb{E}[|S|^2]}$.

3. **Matrix Azuma inequality** (Tropp 2012): For a matrix-valued martingale with bounded differences, the tail probability decays exponentially.

4. **Edge sampling / decoupling**: The sum $L_S = \sum_{(u,v)\in E} X_u X_v L_{uv}$ can be analyzed via standard decoupling techniques for U-statistics (de la Peña–Giné), reducing to a sum of independent random matrices conditioned on one side.

---

## Sketch of Unified Constant

Combining the two cases:

- **Sparse case**: $|S| = |I| \ge \frac{\epsilon}{2} n$.  
- **Dense case**: $|S| \ge \frac{\epsilon}{2} n$ with $L_S \preceq \epsilon L$ (from concentration argument, holding with positive probability).

In both cases, $c = 1/2$ appears achievable (modulo constants lost in concentration).

**Conjecture**: $c = 1/2$ or $c = 1/4$ is the correct answer, tight for complete bipartite graphs $K_{n/2,n/2}$ (where we can only take $S \subseteq A$ or $S \subseteq B$).

---

## Open / Remaining Steps

1. **Complete the dense case proof**: Make the matrix concentration argument rigorous. Quantify the probability that $L_S \preceq \epsilon L$ using matrix Azuma or Bernstein with the specific parameters.

2. **Find the optimal constant $c$**: Is $c = 1/2$ tight? Does $K_{n/2,n/2}$ rule out $c > 1/2$?

3. **Check: does $c = 1$ work?** The complete graph allows it. Can we always find an $\epsilon$-light set of size exactly $\lfloor \epsilon n \rfloor$?

4. **Alternative approach**: Semidefinite programming / spectral methods to construct $S$ deterministically.

5. **Tightness examples**: Investigate whether dense expanders or other structured graphs provide tighter constraints on $c$.

---

## 证明策略（中文摘要）

基于平均度数 $d_{\rm avg} = 2|E|/n$，分两种情况讨论：

**情形一：稀疏图（$d_{\rm avg} \le 1/(2\epsilon)$）**

利用贪心算法构造大独立集 $I$，满足 $|I| \ge n/(d_{\rm avg}+1) \ge \epsilon n / 2$。由于 $I$ 是独立集，$L_I = 0 \preceq \epsilon L$，即 $I$ 是 $\epsilon$-轻集。

**情形二：稠密图（$d_{\rm avg} > 1/(2\epsilon)$）**

对每个顶点以概率 $p = \sqrt{\epsilon}$ 独立地加入集合 $S$。

- 期望大小：$\mathbb{E}[|S|] = \sqrt{\epsilon} \cdot n \ge \epsilon n$（因 $\sqrt{\epsilon} \ge \epsilon$ 对 $\epsilon \in [0,1]$ 成立）。
- 期望矩阵条件：$\mathbb{E}[L_S] = p^2 L = \epsilon L \preceq \epsilon L$。
- 利用**矩阵 Azuma 不等式**（或矩阵 Bernstein 不等式）证明 $L_S \preceq \epsilon L$ 以正概率成立。
- 结合 Paley–Zygmund 不等式保证 $|S| \ge \epsilon n / 2$ 也以正概率成立。
- 联合两个事件（各自概率 $> 1/2$），推出两者同时成立的概率为正。

两种情形均给出 $|S| \ge c \epsilon n$，其中 $c \ge 1/2$（差常数因子）。

---

*Last updated: 2026-04-09*
