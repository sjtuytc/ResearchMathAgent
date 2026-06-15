**Conjecture Extraction Prompt v3**

### **Inputs for this Task**

**1. The Problem:**
```
{problem}
```

**2. Candidate Solution or Solutions:**
```
{solver_subset}
```
**3. Current list of facts, or graders' reports**
```
{facts_and_grader_reports}
```

### **Execution Protocol (MUST BE FOLLOWED METICULOUSLY)**

You will perform an iterative process where a council of experts critiques each proof, clearly articulating holes in the argument. The final result is a **single more rigorous proof** that borrows ideas from provided proofs. It fixes all discovered holes by relying on **clearly-stated conjectures.** If these conjectures were proven, this proof would be complete and correct. The key objective is to use **as few conjectures as possible.**

#### **Persona Descriptions**

*   **The Council of Graders:** A team of specialist personas.
    *   **The Formalist:** A master of logic and rigor. The Formalist's sole focus is on the line-by-line validity of the argument. The Formalist checks for logical fallacies, unstated assumptions, and gaps in reasoning.
    *   **The Strategist:** An expert in mathematical problem-solving approaches. The Strategist evaluates the overall architecture of the solution. Is the chosen strategy sound? Was there a logical hole, or did it miss a simpler path? What is the easiest conjecture that could fill the logical hole?
*   **Advocatus Diaboli:** Tries to give the best possible defense of what the others consider to be a logical hole.
*   **The Conjecture Auditor:** Scourge of lazy conjecturing, with these beliefs:
    (i) *Keep it minimal*: make the conjecture as weak as possible (universal → existential; equality → inequality; exact → range) while still sufficing to bridge the gap.
    (ii) *Make it nontrivial*: it should not just imply *the problem* in a paragraph or two.
    (iii) *Not refutable on easy or small examples* (e.g., graphs on ≤ 5 vertices, the symmetric group, etc.). If a counterexample is found, weaken the conjecture until refutation fails.
    (iv) *Does not re-instantiate a documented dead end.* For each candidate, ask: if the pipeline pursued this conjecture, would it fail by the same mechanism already recorded under some IPT-N — even under different parameters, different framing, or cosmetic relabeling? If so, reject or reformulate. Log the IPT-N matched.
    *The parent problem is carefully designed, so its hypotheses are almost certainly all necessary; a strengthening of the parent (e.g., "for all n" when only multiples of 4 are needed) is likely false.*
*   **The Chief Architect:** The final arbiter who oversees the process and synthesizes the final, refined solution along with clearly stated conjectures.

---
### **Instructions**
**Configuration:** `MAX_GRADING_ROUNDS: 3`

**<internal_monologue>**

*(You will perform the following stages silently. The final output will be assembled at the end.)*

**--- BEGIN GRADING FORUM ---**

1.  **Initial Analysis (Round 0):**
    *   The Formalist and the Strategist will independently read each provided solution and write an `Initial_Critique` (containing at most 2-3 bullet points) on its potential flaws and strengths from their perspective. The Chief Architect will combine these into a single report for each solution and will also create a single `Conjecture_list` that is initially empty.

2.  **Iterative Refinement (Rounds 1 to MAX_GRADING_ROUNDS):**
    *   Initialize `round_count = 1`.
    *   **BEGIN REFINEMENT LOOP:**
        *   a. **Cognitive Reset:** The Chief Architect writes a Haiku summarizing the current state of the proof to clear the context window of repetitive phrasing.
        *   b. **Council's Critique:** For each provided solution, the Chief Architect combines their initial findings and results of the previous round into a single, consolidated `Current_Critique` containing, for each proof, the gaps identified so far. This document should list all identified weaknesses.
        *   c. **The Defense:** The Advocatus Diaboli will read the `Current_Critique` and write a `Rebuttal`. For each weakness, this argues why it is either not a flaw, a minor issue, or a misunderstanding of the proof's intent.
        *   d. **Refinement and Judgment:** The Council reads the `Rebuttal`. They must now produce a `Refined_Critique`. They will decide which of their points stand, which should be dropped in light of the defense, and which need to be re-phrased to be more precise. For each point that stands, they must explicitly state why the `Rebuttal` was unconvincing. For each gap in the solution's logic, **The Strategist** must first attempt to bridge it using standard deduction. Only if this fails may they propose a conjecture. The conjecture must be phrased in a *clear and self-contained way* so that it can be understood without access to the rest of the proof. **The Conjecture Auditor** then applies its three beliefs in turn to each proposed conjecture. Each weakening attempt and each small-example refutation attempt is logged in the `Refined_Critique`. The version added to `Conjecture_list` is the one that survives the Auditor.
        *   e. **Consolidation of Conjectures:** The Council deliberates on ways to shorten the `Conjecture_list` via suitable rephrasing. They may choose to ignore proofs that are hopelessly broken and require too many fixes.
        *   f. **Halt Condition:** The loop will halt if the `Refined_Critique` is substantially unchanged from the `Current_Critique` of the same round, or if `round_count` reaches `MAX_GRADING_ROUNDS`.
        *   g. Increment `round_count` and repeat the loop, using the `Refined_Critique` as the starting point for the next round's `Current_Critique`.
    *   **END REFINEMENT LOOP.**
    *   The final `Refined_Critique`.

3.  **Final Verdict (The Chief Architect):**
    *   **Coroner's Report:** The Chief Architect will write a one-paragraph "Coroner's Report" on each proof and assign a grade out of 7. Major gaps in reasoning incur significant penalty, and a grade of 5 or higher implies a near-correct proof.
    *   **Synthesis:** The Chief Architect will now synthesize the `Final_Council_Report` and all preceding logs into a single final proof draft that combines the best ideas of all input proofs and, together with `Conjecture_list`, represents a candidate solution path.

    The new proof starts by stating new conjectures, phrased in a self-contained way (i.e., can be completely understood by somebody who has not seen *The Problem*). This is followed by a rigorous proof that is correct and complete if the conjectures are assumed. *No sloppiness is allowed in this proof* (e.g., asserting something holds for all N after checking for N = 1 to 3, or appealing to an unnamed "well-known result").

**--- END GRADING FORUM ---**

**</internal_monologue>**

---
### **Final Output Format**

Your final response must be structured in **exactly** the following two parts.

**Part 1: The Grading Log**

*(Render a structured summary of the grading process.)*

*   **Round 1 Haiku:** [Insert Haiku]
*   **Council's Critique:** (List of strengths/weaknesses)
*   **Advocatus Diaboli's Rebuttals:** (Point-by-point defense)
*   **Final Refined Critique:** (Final list of points for this round, with justifications against the rebuttal)

*(Repeat for subsequent rounds as necessary. Include the Haiku for each round.)*

**Part 2: Completed Proof with Conjectures**

1.  **List of Conjecture(s):** Each must be a self-contained mathematical statement that can be completely understood by somebody who has not seen *The Problem*.
2.  **Negation of Conjectures:** List the *negation* of each conjecture appearing in (1). This negation must be true iff the conjecture is false.
3.  **Rigorous Proof:** A rigorous proof for *The Problem* assuming the conjecture(s).
