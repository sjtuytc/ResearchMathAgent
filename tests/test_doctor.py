from __future__ import annotations

import unittest
from argparse import Namespace

from rma.doctor import run_doctor


class DoctorTest(unittest.TestCase):
    def test_doctor_passes_for_repo_root(self) -> None:
        self.assertEqual(run_doctor(Namespace(repo_root=".")), 0)


if __name__ == "__main__":
    unittest.main()
