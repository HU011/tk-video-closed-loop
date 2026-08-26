import unittest

from integrations.seedance_client import SeedanceClient


class SeedanceClientTests(unittest.TestCase):
    def test_extract_apimart_task_id(self):
        client = SeedanceClient()
        task_id = client._extract_task_id(
            {
                "code": 200,
                "data": [{"status": "submitted", "task_id": "task_123"}],
            }
        )
        self.assertEqual(task_id, "task_123")

    def test_extract_video_and_tail_frame_urls(self):
        client = SeedanceClient()
        data = {
            "code": 200,
            "data": {
                "status": "completed",
                "result": {
                    "videos": [{"url": ["https://upload.apimart.ai/f/video/out.mp4"]}],
                    "last_frame_url": "https://upload.apimart.ai/f/image/tail.png",
                },
            },
        }
        self.assertEqual(client._extract_video_url(data), "https://upload.apimart.ai/f/video/out.mp4")
        self.assertEqual(client._extract_tail_frame_url(data), "https://upload.apimart.ai/f/image/tail.png")


if __name__ == "__main__":
    unittest.main()

