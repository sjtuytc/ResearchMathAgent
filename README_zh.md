# RMA：面向研究级数学问题的智能体系统

<div align="center">

[![arXiv](https://img.shields.io/badge/arXiv-2605.22875-b31b1b.svg)](https://arxiv.org/abs/2605.22875)
[![GitHub Stars](https://img.shields.io/github/stars/sjtuytc/ResearchMathAgent?style=flat-square)](https://github.com/sjtuytc/ResearchMathAgent/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/sjtuytc/ResearchMathAgent?style=flat-square)](https://github.com/sjtuytc/ResearchMathAgent/network/members)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://github.com/sjtuytc/ResearchMathAgent/pulls)

**语言：** [English](README.md) | 中文

</div>

---

## 核心亮点

> RMA 是首个面向**研究级数学证明**的智能体框架——不是竞赛题，不是形式化定理证明——通过专门化智能体、结构化共享记忆与迭代验证反馈协同工作。

| 特性 | 说明 |
|------|------|
| **研究级数学问题** | First Proof 基准：10 道由数学专家贡献的开放性研究问题，横跨 10 个不同领域 |
| **多智能体流水线** | 初始化器 → 提议器 → 验证器 → 精炼器，通过结构化共享记忆协调 |
| **领先实验结果** | 在 First Proof 上解决 **8 / 10** 道问题，超越 GPT-5.2R 与 Aletheia |
| **双 Claude 后端** | Anthropic Messages API（按 token 付费）*或* Claude Code 本地 CLI（Pro/Max 订阅额度） |
| **实时 Web 界面** | 逐步流式输出、实时 PDF 预览、问题追踪器、token 费用显示 |
| **自主每日工作器** | 无需人工干预，定时运行求解器，将有日期的报告写入 `documents/` |
| **基准公平沙箱** | 代码层面强制污染边界——求解器绝不读取历史解答 |
| **多智能体 GitHub Issues API** | REST 接口 (`/api/gh/issues`) 让多个智能体在真实 GitHub Issues 上协作 |

---

## 摘要

<details>
<summary>展开完整摘要</summary>

我们提出 **Research Math Agents (RMA)**，一个面向研究级数学问题自动化推理的智能体框架。与以往聚焦于竞赛数学或形式化定理证明的研究不同，RMA 针对需要长程推理、文献溯源与迭代证明精炼的研究级数学问题。RMA 将研究级证明求解分解为若干专门模块：问题分析、文献检索与理解、公平比较、知识库构建以及证明验证，所有模块通过初始化器、提议器和验证器智能体经由共享结构化记忆统一协调。在这一统一框架内，各智能体以多角色、多轮次工作流协同运作，通过迭代反馈不断生成、精炼和验证候选证明。我们在 First Proof 基准上对 RMA 进行评估，该基准包含十位来自不同领域的数学专家贡献的十道研究级问题。经专家全面评估，RMA 在 First Proof 基准上超越了包括 GPT-5.2R 和 Aletheia 在内的强基线，解决了十道问题中的八道，并产出了逻辑更严谨、可读性更强的证明。全面的消融研究进一步表明，性能提升源于结构化推理模块、迭代精炼与验证器反馈的协同作用，而非单一组件。

</details>

![Teaser](figures/teaser.png)

---

## 系统概览

![Model](figures/model.png)

RMA 聚焦于**研究级数学**（而非竞赛数学或形式化定理证明），综合运用以下专门模块：问题分析、文献检索与理解、公平比较、知识库构建和证明验证。

在多角色、多轮次工作流中，初始化器/提议器/验证器智能体共享结构化记忆，迭代生成、精炼和验证候选证明。在 First Proof 基准上，RMA 通过结构化模块、迭代精炼和验证器反馈报告了优于强基线的结果。

---

## 快速开始

```bash
# 1. 安装
pip install -e ".[webapp]"

# 2. 设置 API 密钥（或使用 Claude Code 订阅——详见下方"Claude 后端"）
export ANTHROPIC_API_KEY="<你的密钥>"

# 3. 求解一道问题
rma solve q6 --model-name claude-opus-4-8

# 4. 启动 Web 界面
python -m webapp          # → http://127.0.0.1:8000
```

---

## 仓库结构

<details>
<summary>展开目录树</summary>

```
ResearchMathAgent/
├── problems/             # 基准问题陈述（q1..q10 .tex 文件）
├── skills/               # 求解器使用的数学研究技能指令
├── final_solutions/      # 已发布/参考证明——不作为求解器输入
├── output_solutions/     # 求解器输出目录（写入目标）
├── rma/                  # CLI 工具：parse / propose / verify / refine / solve
├── webapp/               # 实时 Web 应用（FastAPI + 原生 JS）
│   └── README.md         # Web 应用详细说明
├── documents/            # 自主工作器生成的每日报告
├── config/default.yaml   # 项目路径与执行层级预设
└── main.tex              # 论文源文件
```

- `problems/` → `final_solutions/` 的边界在代码层面强制执行；求解器绝不读取历史解答。
- `output_solutions/` 是所有 `rma solve` 运行的写入目标。
- 剩余工程路线图见 [TODO.md](TODO.md)。

</details>

---

## 命令行工具（CLI）

安装后即可使用 `rma` 命令：

```bash
pip install -e .
rma doctor        # 环境健康检查
```

或不安装直接运行：

```bash
python -m rma doctor
```

<details>
<summary>分阶段流水线（parse / propose / verify / refine）</summary>

流水线为：

```
parse → propose → verify → refine
```

每个阶段均可单独运行，后续阶段会自动初始化缺失的前置产物。

```bash
rma parse q6
rma propose q6
rma verify q6
rma refine q6
```

指定实验名称和模型：

```bash
rma parse q6    --exp-name proofs_v1_june13 --model-name rma-skeleton
rma propose q6  --exp-name proofs_v1_june13 --model-name rma-skeleton
rma verify q6   --exp-name proofs_v1_june13 --model-name rma-skeleton
rma refine q6   --exp-name proofs_v1_june13 --model-name rma-skeleton
```

各阶段输出：

| 阶段 | 写入文件 |
|------|---------|
| `parse` | `parsed_problem.json`、`problem_analysis.md` |
| `propose` | `qN_solution.tex`、版本化提议产物 |
| `verify` | 验证报告（JSON + Markdown），默认渲染 PDF |
| `refine` | 根据最新报告重写 `qN_solution.tex` |

`verify` 检查 LaTeX/产物正确性以及数学完整性门控（证明长度、子命题结构、子证明、假设审计、引用或推导、边界情形证明）。

</details>

<details>
<summary>rma solve — 完整求解循环</summary>

`rma solve` 统筹 `parse → propose → verify`，验证失败时调用 `refine`，最多重复 `--max-rounds` 轮。只有当验证器所有门控均通过时，运行才标记为 `verified`。

```bash
# 求解单道问题
rma solve q6

# 求解全部 10 道问题
rma solve --all

# 指定实验名称 + 骨架模型（流水线测试）
rma solve --all --exp-name proofs_test_all_june13 --model-name rma-skeleton

# 执行层级（记录在元数据中）
rma solve q6 --tier budget      # 可选 standard / pro

# 限制精炼轮数
rma solve q6 --max-rounds 3

# 使用数学研究技能
rma solve q6 --skill-path skills/math-research/SKILL.md

# 仅写入 .tex（跳过 PDF 渲染）
rma solve q6 --no-render
```

**输出目录结构：**

```
output_solutions/proofs_v1_june13_rma-skeleton/
  q6_solution.tex
  q6_solution.pdf
  q6/
    input/problem.tex
    artifacts/
      metadata.json
      status.json
      report.md
      parsed_problem.json
      problem_analysis.md
      proposals/proposal_001.tex
      verifications/verification_001.json
      refinements/
```

**终端输出示例：**

```
RMA solve
tier: standard
skill: skills/math-research/SKILL.md
status: needs_refinement
output: output_solutions/proofs_v1_june13_rma-skeleton
solution: output_solutions/proofs_v1_june13_rma-skeleton/q6_solution.tex
verification: .../verification_003.json
```

</details>

<details>
<summary>Claude 后端——API 密钥 vs 订阅额度</summary>

**Anthropic Messages API**（按 token 付费）：

```bash
export ANTHROPIC_API_KEY="<你的密钥>"
rma solve q6 --model-name claude-opus-4-8
rma solve --all --model-name claude-sonnet-4-6 --max-rounds 3
```

macOS 用户可将密钥存入钥匙串，避免每次导出：

```bash
security add-generic-password -U -a "$USER" -s rma_anthropic_api_key -w "<密钥>"
rma solve q6 --model-name claude-sonnet-4-6    # 自动从钥匙串读取
```

显式指定 API 后端：

```bash
rma solve q6 --model-provider anthropic --model-name claude-opus-4-8
```

**Claude Code**（Pro/Max 订阅额度——不消耗 API 额度）：

```bash
claude                  # 首次登录，完成浏览器授权
rma solve q6 --model-provider claude-code --model-name claude-code
rma solve --all --model-provider claude-code --model-name claude-code --max-rounds 3
```

`claude-code` 驱动本地 `claude -p` 无头 CLI。若希望使用订阅计费而非 API 计费，请取消设置 `ANTHROPIC_API_KEY`。

**自动检测：** `--model-provider auto`（默认）对 `rma-skeleton` 使用 Claude Code，对任意 `claude-*` 模型名称使用 Anthropic API。

</details>

---

## Web 应用

```bash
pip install -e ".[webapp]"
python -m webapp          # → http://127.0.0.1:8000
```

在远程服务器上，转发端口到本地：

```bash
ssh -L 8000:localhost:8000 user@server
```

<details>
<summary>Web 应用功能列表</summary>

- **问题（Question）标签页** — 以 KaTeX 渲染 `.tex` 问题陈述；支持原始/渲染切换
- **议题（Issue）标签页** — 类 GitHub 风格的每题议题追踪器（多智能体评论线程、状态、标签）；同时暴露 `/api/gh/issues` 用于直接控制 GitHub Issues
- **智能体（Agent）标签页** — 实时流式运行求解器，显示推理过程 + 工具调用 + 渲染数学公式 + token 费用
- **文档（Documents）标签页** — 浏览有日期的每日报告；支持手动触发智能体运行
- **双 Claude 后端** — API 密钥或本地 Claude Code 订阅（`claude` CLI 无头模式，消耗 Pro/Max 订阅额度而非 API 额度）
- **逐步实时流** — 推理块、助手文本、工具调用及结果实时显示
- **停止按钮** — `POST /api/cancel` 立即终止后端进程组，停止消耗订阅额度
- **活跃运行面板** — 列出所有进行中的运行，每个运行均有独立停止按钮，便于并行运行管理
- **PDF 预览** — 在线编译 `solution.tex`（需服务器端 LaTeX）；无 LaTeX 时优雅降级
- **Token / 费用显示** — 每轮用量图表与每张卡片的费用标注
- **自主每日工作器** — `python -m webapp.daily` 每晚自动运行求解器，写入 `documents/YYYY-MM-DD.md`，并将每次运行记录到对应问题的议题线程

</details>

<details>
<summary>多智能体 GitHub Issues API</summary>

多个求解智能体可通过 Web 应用的 REST API 在真实 GitHub Issues 上协作。所有接口均在 `/api/gh/` 下：

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/gh/status` | GET | 检查 token 状态与仓库名 |
| `/api/gh/issues?problem_id=q6` | GET | 列出议题（按 `problem:q6` 标签筛选） |
| `/api/gh/issues` | POST | 创建议题 `{problem_id, title, body, labels}` |
| `/api/gh/issues/{n}` | GET | 获取议题及评论 |
| `/api/gh/issues/{n}/comment` | POST | 添加评论 `{body}` |
| `/api/gh/issues/{n}` | PATCH | 更新 `{title, state, labels, body}` |
| `/api/gh/issues/{n}/close` | POST | 关闭议题 |
| `/api/gh/issues/{n}/reopen` | POST | 重新打开议题 |
| `/api/gh/search?q=...` | GET | GitHub 搜索语法 |

写操作需要 `GITHUB_TOKEN` 环境变量（细粒度 PAT，Issues 读写权限）。读操作无需认证（60 次/小时）。

</details>

---

## 求解器污染边界

<details>
<summary>公平评估规则</summary>

求解器必须将 First Proof 官方解答和历史 AI 生成解答视为**封锁输入**。求解过程可以读取：

- `problems/` — 基准问题陈述
- `skills/` — 数学研究技能指令
- 同次运行的产物（由同一运行的前序阶段创建）

求解器**绝不**读取、grep、glob、摘要、渲染或以任何方式使用以下目录中的已有文件：

- `final_solutions/`
- `output_solutions/`
- `baselines/`
- First Proof 官方解答页面或衍生解答材料

`output_solutions/` 仅允许作为**写入**目标。历史输出目录和无关现有解答产物仍属封锁范围。

主要求解器命令：

```bash
rma solve q6      # 仅读取 problems/q6.tex，写入全新产物
rma solve --all   # 在全部 10 道问题上进行公平基准评测
```

</details>

---

## 论文编译

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

---

## 致谢

感谢 **PoggioAI** 开源 `PoggioAI_MSc`，其系统组织方向和 README 结构为本项目提供了启发。同时感谢 **[TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany)** 团队开源其智能体循环框架和问题/议题工作区设计，这启发了 RMA Web 应用的架构。

---

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=sjtuytc/ResearchMathAgent&type=Date)](https://star-history.com/#sjtuytc/ResearchMathAgent&Date)

---

## 引用

```bibtex
@article{zhao2026rma,
  title={RMA: an Agentic System for Research-Level Mathematical Problems},
  author={Zhao, Zelin and Yuan, Bo and Choi, Jaemoo and Chen, Yongxin},
  journal={arXiv preprint arXiv:2605.22875},
  year={2026}
}
```
