import unittest

from core.paths import ROOT_DIR, ensure_under_root
from services.analyzer import score_creator, score_video


class AnalyzerTests(unittest.TestCase):
    def test_hot_video_score_rewards_engagement_and_orders(self):
        score, reason = score_video(
            {
                "views": 200000,
                "likes": 12000,
                "comments": 600,
                "shares": 1800,
                "orders": 250,
                "gmv": 5000,
                "duration_seconds": 24,
            }
        )
        self.assertGreater(score, 60)
        self.assertIn("互动率", reason)

    def test_free_sample_candidate_score(self):
        score, reasons = score_creator(
            {
                "sample_received_count": 6,
                "posted_video_count": 1,
                "order_count": 0,
                "gmv": 0,
                "follower_count": 60000,
            }
        )
        self.assertGreaterEqual(score, 50)
        self.assertTrue(reasons)

    def test_path_boundary_rejects_outside_project(self):
        with self.assertRaises(ValueError):
            ensure_under_root(ROOT_DIR.parent / "outside.txt")


if __name__ == "__main__":
    unittest.main()

