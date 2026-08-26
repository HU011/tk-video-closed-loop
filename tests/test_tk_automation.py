import unittest

from tk_automation.collectors.completed_video_links import CompletedVideoLinkCollector
from tk_automation.collectors.backend_api import add_query_params, find_first_bool, find_first_value, render_template
from tk_automation.collectors.network_monitor import parse_methods, sanitize_headers
from tk_automation.parsers.video_links import extract_video_urls_from_text, normalize_video_url


class TKAutomationTests(unittest.TestCase):
    def test_extract_video_urls_from_text(self):
        text = "done https://www.tiktok.com/@demo/video/7123456789012345678?lang=en"
        urls = extract_video_urls_from_text(text)
        self.assertEqual(urls, ["https://www.tiktok.com/@demo/video/7123456789012345678"])

    def test_normalize_video_url_removes_query(self):
        self.assertEqual(
            normalize_video_url("https://www.tiktok.com/@u/video/123?is_copy_url=1"),
            "https://www.tiktok.com/@u/video/123",
        )

    def test_api_data_extracts_completed_nested_rows(self):
        data = {
            "data": {
                "list": [
                    {
                        "creator_username": "demo",
                        "video_link": "https://www.tiktok.com/@demo/video/100?lang=en",
                        "publish_status": "published",
                    },
                    {
                        "creator_username": "demo",
                        "video_link": "https://www.tiktok.com/@demo/video/200",
                        "publish_status": "draft",
                    },
                ]
            }
        }
        records = CompletedVideoLinkCollector().collect_api_data(data, account_name="shop_a")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].account_name, "shop_a")
        self.assertEqual(records[0].video_url, "https://www.tiktok.com/@demo/video/100")

    def test_backend_request_helpers_render_page_values(self):
        self.assertEqual(
            add_query_params("/api/videos?status=completed", {"page": 2, "page_size": 20}),
            "/api/videos?status=completed&page=2&page_size=20",
        )
        self.assertEqual(render_template({"page": "{page}", "size": "{page_size}"}, page=3, page_size=50), {"page": "3", "size": "50"})

    def test_backend_cursor_helpers_read_nested_response(self):
        data = {"data": {"pagination": {"next_cursor": "abc", "has_more": "false"}}}
        self.assertEqual(find_first_value(data, ("next_cursor",)), "abc")
        self.assertFalse(find_first_bool(data, ("has_more",)))

    def test_network_monitor_sanitizes_sensitive_headers(self):
        headers = sanitize_headers({"Cookie": "sid=secret", "authorization": "Bearer token", "content-type": "application/json"})
        self.assertEqual(headers["Cookie"], "***")
        self.assertEqual(headers["authorization"], "***")
        self.assertEqual(headers["content-type"], "application/json")

    def test_network_monitor_parse_methods(self):
        self.assertEqual(parse_methods("get, post "), ("GET", "POST"))


if __name__ == "__main__":
    unittest.main()
