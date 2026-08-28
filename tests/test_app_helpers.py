import unittest
from pathlib import Path

from app import _limit, _path_is_under
from core.paths import ROOT_DIR, STATIC_DIR


class AppHelperTests(unittest.TestCase):
    def test_limit_clamps_invalid_values(self):
        self.assertEqual(_limit({"limit": "-1"}), 1)
        self.assertEqual(_limit({"limit": "9999"}), 500)
        self.assertEqual(_limit({"limit": "bad"}), 200)

    def test_path_is_under_rejects_same_prefix_sibling(self):
        self.assertFalse(_path_is_under(ROOT_DIR / "static_evil" / "index.html", STATIC_DIR))
        self.assertTrue(_path_is_under(STATIC_DIR / "index.html", STATIC_DIR))

    def test_env_example_uses_mock_defaults(self):
        text = Path(".env.example").read_text(encoding="utf-8")
        self.assertIn("GEMINI_PROVIDER=mock", text)
        self.assertIn("GEMINI_REQUEST_FORMAT=native", text)
        self.assertIn("SEEDANCE_PROVIDER=mock", text)


if __name__ == "__main__":
    unittest.main()
