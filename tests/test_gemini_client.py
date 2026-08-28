from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.paths import ROOT_DIR
from integrations import gemini_client as gemini_module
from integrations.gemini_client import GeminiClient


class FakeAPIMart:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def json_request(self, url: str, body: dict, method: str = "POST") -> dict:
        self.calls.append((url, body))
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"prompt":"use product image","shot_notes":["match camera"],"warnings":[]}',
                            }
                        ]
                    }
                }
            ]
        }


class GeminiClientTests(unittest.TestCase):
    def test_native_request_sends_video_as_inline_data(self):
        fake_settings = SimpleNamespace(
            gemini_provider="apimart",
            gemini_request_format="native",
            gemini_endpoint="",
            gemini_api_key="key",
            gemini_model="gemini-2.5-flash",
            apimart_base_url="https://api.apimart.ai",
            apimart_chat_endpoint="https://api.apimart.ai/v1/chat/completions",
            public_base_url="",
        )
        runtime_dir = ROOT_DIR / "runtime"
        runtime_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime_dir) as temp_dir:
            source = Path(temp_dir) / "segment.mp4"
            product = Path(temp_dir) / "product.jpg"
            tail = Path(temp_dir) / "tail.jpg"
            source.write_bytes(b"fake video bytes")
            product.write_bytes(b"fake image bytes")
            tail.write_bytes(b"fake tail bytes")

            with patch.object(gemini_module, "settings", fake_settings):
                client = GeminiClient(api_key="key", model="gemini-2.5-flash")
                fake_api = FakeAPIMart()
                client.apimart = fake_api
                result = client.build_segment_prompt(2, 4, source, source, product, tail)

        self.assertEqual(result["prompt"], "use product image")
        url, body = fake_api.calls[0]
        self.assertEqual(url, "https://api.apimart.ai/v1beta/models/gemini-2.5-flash:generateContent")
        parts = body["contents"][0]["parts"]
        video_parts = [part for part in parts if "inlineData" in part and part["inlineData"]["mimeType"] == "video/mp4"]
        image_parts = [part for part in parts if "inlineData" in part and part["inlineData"]["mimeType"] == "image/jpeg"]
        self.assertEqual(len(video_parts), 1)
        self.assertEqual(len(image_parts), 2)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        first_text = parts[0]["text"]
        self.assertIn("只基于当前上传的源视频片段", first_text)
        self.assertNotIn("分析完整原视频", first_text)


if __name__ == "__main__":
    unittest.main()
