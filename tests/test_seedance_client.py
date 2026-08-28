import unittest

from integrations.seedance_client import SeedanceClient


class FakeAPIMart:
    def __init__(self):
        self.calls = []

    def upload_image(self, path):
        return str(path)

    def json_request(self, url, body=None, method="POST"):
        self.calls.append((url, body, method))
        return {
            "video_url": "https://upload.apimart.ai/f/video/out.mp4",
            "last_frame_url": "https://upload.apimart.ai/f/image/tail.png",
        }


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

    def test_seedance_request_uses_reference_video_and_tail_reference_image(self):
        client = SeedanceClient()
        fake = FakeAPIMart()
        client.apimart = fake

        video_url, tail_url = client._submit_and_wait_apimart(
            prompt="复刻当前片段",
            source_segment_path="https://example.com/source_segment.mp4",
            product_image_path="https://example.com/product.jpg",
            duration=15,
            first_frame_path="https://example.com/tail.jpg",
        )

        self.assertEqual(video_url, "https://upload.apimart.ai/f/video/out.mp4")
        self.assertEqual(tail_url, "https://upload.apimart.ai/f/image/tail.png")
        _url, body, method = fake.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(body["video_urls"], ["https://example.com/source_segment.mp4"])
        self.assertEqual(body["image_urls"], ["https://example.com/tail.jpg", "https://example.com/product.jpg"])
        self.assertTrue(body["return_last_frame"])
        self.assertNotIn("image_with_roles", body)


if __name__ == "__main__":
    unittest.main()
