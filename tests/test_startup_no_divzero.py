"""Regression guard for S2 ticket tk-20261105-172645-c904.

An injected ``_injected = 1 / 0`` inside ``order_app.main()`` made every
restarted process exit immediately with ``ZeroDivisionError``.  This test
fails if a literal division/modulo by zero is added to the application
entry points again.
"""

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = ("order_app.py", "business_app.py")
ZERO_DIVISION_OPS = (ast.Div, ast.FloorDiv, ast.Mod)


class StartupZeroDivisionGuard(unittest.TestCase):
    def test_no_literal_division_by_zero(self):
        for name in TARGETS:
            path = ROOT / name
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders = []
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ZERO_DIVISION_OPS):
                    right = node.right
                    if isinstance(right, ast.Constant) and right.value == 0:
                        offenders.append(node.lineno)
            with self.subTest(file=name):
                self.assertEqual(
                    offenders, [],
                    f"{name} contains a literal division/modulo by zero at lines {offenders}",
                )


if __name__ == "__main__":
    unittest.main()
