from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from rma.solve import run_parse, run_propose, run_refine, run_solve, run_verify


class SolveTest(unittest.TestCase):
    def _args(
        self,
        output: Path,
        problem: str | None = "q6",
        all_problems: bool = False,
        no_render: bool = True,
        model_name: str = "rma-skeleton",
        model_provider: str = "auto",
    ) -> Namespace:
        return Namespace(
            problem=problem,
            all=all_problems,
            tier="standard",
            output=str(output),
            exp_name="proofs_test",
            model_name=model_name,
            model_provider=model_provider,
            no_render=no_render,
            max_rounds=3,
            skill_path="skills/math-research/SKILL.md",
            repo_root=".",
        )

    def test_solve_creates_single_problem_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "q6_run"
            result = run_solve(self._args(output))

            self.assertEqual(result, 1)
            self.assertTrue((output / "q6" / "input" / "problem.tex").is_file())
            self.assertTrue((output / "q6_solution.tex").is_file())
            self.assertTrue((output / "q6" / "artifacts" / "parsed_problem.json").is_file())
            self.assertTrue((output / "q6" / "artifacts" / "proposals" / "proposal_001.tex").is_file())
            self.assertTrue((output / "q6" / "artifacts" / "verifications" / "verification_001.json").is_file())
            self.assertTrue((output / "q6" / "artifacts" / "verifications" / "verification_003.json").is_file())
            solution = (output / "q6_solution.tex").read_text(encoding="utf-8")
            self.assertIn(r"\varepsilon", solution)
            self.assertNotIn("No proof has been generated", solution)
            metadata = json.loads((output / "q6" / "artifacts" / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["problem_id"], "q6")
            self.assertEqual(metadata["status"], "needs_refinement")
            self.assertEqual(metadata["skill"]["relative_path"], "skills/math-research/SKILL.md")
            self.assertEqual(metadata["skill"]["name"], "math-research")
            self.assertIn("final_solutions", metadata["blocked_input_dirs"])
            self.assertIn("output_solutions", metadata["blocked_input_dirs"])
            verification = json.loads((output / "q6" / "artifacts" / "verifications" / "verification_003.json").read_text(encoding="utf-8"))
            self.assertFalse(verification["passed"])
            self.assertEqual(verification["checks"]["mathematical_completeness"], "failed")

    def test_solve_rejects_invalid_problem_id(self) -> None:
        result = run_solve(self._args(Path("/tmp/unused"), problem="q11"))

        self.assertEqual(result, 1)

    def test_solve_all_creates_unified_initial_solutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "all_run"
            result = run_solve(self._args(output, problem=None, all_problems=True))

            self.assertEqual(result, 1)
            for i in range(1, 11):
                solution = output / f"q{i}_solution.tex"
                status = json.loads((output / f"q{i}" / "artifacts" / "status.json").read_text(encoding="utf-8"))
                text = solution.read_text(encoding="utf-8")
                self.assertTrue(solution.is_file())
                self.assertEqual(status["status"], "needs_refinement")
                self.assertFalse(status["completed"])
                self.assertNotIn("draft", text.lower())
                self.assertNotIn("placeholder", text.lower())
                self.assertNotIn("not_implemented", text)
                self.assertNotIn("A problem-specific solver has not been implemented", text)

    def test_stage_commands_are_individually_runnable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "stage_run"

            self.assertEqual(run_parse(self._args(output)), 0)
            parsed = output / "q6" / "artifacts" / "parsed_problem.json"
            self.assertTrue(parsed.is_file())

            self.assertEqual(run_propose(self._args(output)), 0)
            self.assertTrue((output / "q6_solution.tex").is_file())

            self.assertEqual(run_verify(self._args(output)), 1)
            verification = output / "q6" / "artifacts" / "verifications" / "verification_001.json"
            self.assertTrue(verification.is_file())
            verification_data = json.loads(verification.read_text(encoding="utf-8"))
            self.assertFalse(verification_data["passed"])
            self.assertEqual(verification_data["checks"]["mathematical_completeness"], "failed")

            self.assertEqual(run_refine(self._args(output)), 0)
            refinement = output / "q6" / "artifacts" / "refinements" / "refinement_001.json"
            self.assertTrue(refinement.is_file())
            self.assertEqual(json.loads(refinement.read_text(encoding="utf-8"))["action"], "rewrote_solution")

    def test_verify_autoruns_missing_prior_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "auto_run"
            self.assertEqual(run_verify(self._args(output)), 1)
            self.assertTrue((output / "q6" / "artifacts" / "parsed_problem.json").is_file())
            self.assertTrue((output / "q6" / "artifacts" / "proposals" / "proposal_001.tex").is_file())
            self.assertTrue((output / "q6" / "artifacts" / "verifications" / "verification_001.json").is_file())

    def test_claude_api_model_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "claude_api_missing_key"
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False), patch(
                "rma.models._load_anthropic_api_key_from_keychain",
                return_value=None,
            ):
                result = run_propose(self._args(output, model_name="claude-sonnet-4-6"))

            self.assertEqual(result, 1)
            self.assertTrue((output / "q6" / "artifacts" / "parsed_problem.json").is_file())
            self.assertFalse((output / "q6_solution.tex").exists())

    def test_claude_code_model_requires_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "claude_code_missing_cli"
            with patch("rma.models.shutil.which", return_value=None):
                result = run_propose(self._args(output, model_name="claude-code", model_provider="claude-code"))

            self.assertEqual(result, 1)
            self.assertTrue((output / "q6" / "artifacts" / "parsed_problem.json").is_file())
            self.assertFalse((output / "q6_solution.tex").exists())


if __name__ == "__main__":
    unittest.main()
