import unittest

from tk_automation.collectors.completed_video_links import CompletedVideoLinkCollector
from tk_automation.collectors.backend_api import add_query_params, find_first_bool, find_first_value, render_template
from tk_automation.collectors.discovery import suggest_backend_api
from tk_automation.collectors.network_monitor import parse_methods, sanitize_headers, sanitize_post_data, sanitize_query
from tk_automation.parsers.video_links import extract_video_urls_from_text, looks_like_video_url, normalize_video_url


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

    def test_extract_short_tiktok_video_url(self):
        urls = extract_video_urls_from_text("done https://vt.tiktok.com/ZSNabc123/?share_app_id=123")
        self.assertEqual(urls, ["https://vt.tiktok.com/ZSNabc123"])

    def test_looks_like_video_url_rejects_images(self):
        self.assertTrue(looks_like_video_url("https://example.com/file/out.mp4?token=abc"))
        self.assertFalse(looks_like_video_url("https://example.com/file/cover.jpg"))

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

    def test_api_data_builds_video_url_and_keeps_metrics(self):
        data = {
            "data": {
                "list": [
                    {
                        "creator_username": "@demo",
                        "item_id": "300",
                        "publish_status": "published",
                        "video_title": "metric row",
                        "play_count": "12345",
                        "like_count": "234",
                        "comment_count": "12",
                        "share_count": "8",
                        "product_order_count": "5",
                        "video_gmv": "321.5",
                        "duration": "18",
                    }
                ]
            }
        }
        record = CompletedVideoLinkCollector().collect_api_data(data, account_name="shop_a")[0]
        row = record.to_video_row()
        self.assertEqual(record.video_url, "https://www.tiktok.com/@demo/video/300")
        self.assertEqual(row["views"], "12345")
        self.assertEqual(row["orders"], "5")
        self.assertEqual(row["gmv"], "321.5")
        self.assertEqual(row["duration_seconds"], "18")

    def test_api_data_does_not_fallback_import_pending_video(self):
        records = CompletedVideoLinkCollector().collect_api_data(
            {"list": [{"creator_username": "demo", "video_link": "https://www.tiktok.com/@demo/video/400", "publish_status": "pending"}]},
            account_name="shop_a",
        )
        self.assertEqual(records, [])

    def test_api_data_does_not_treat_generic_id_as_video_id(self):
        records = CompletedVideoLinkCollector().collect_api_data(
            {"list": [{"creator_username": "demo", "id": "500", "publish_status": "published"}]},
            account_name="shop_a",
        )
        self.assertEqual(records, [])

    def test_collect_text_derives_creator_from_tiktok_url(self):
        records = CompletedVideoLinkCollector().collect_text("https://www.tiktok.com/@demo_creator/video/600")
        self.assertEqual(records[0].username, "demo_creator")

    def test_api_data_rejects_generic_image_url(self):
        records = CompletedVideoLinkCollector().collect_api_data(
            {"list": [{"url": "https://example.com/cover.jpg", "publish_status": "published", "title": "not video"}]},
            account_name="shop_a",
        )
        self.assertEqual(records, [])

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

    def test_network_monitor_sanitizes_query_and_post_data(self):
        self.assertEqual(sanitize_query({"csrf_token": "secret", "page": "1"}), {"csrf_token": "***", "page": "1"})
        self.assertEqual(
            sanitize_post_data('{"token":"secret","page":1,"filter":{"status":"published"}}'),
            '{"token": "***", "page": 1, "filter": {"status": "published"}}',
        )
        self.assertEqual(sanitize_post_data("csrf_token=secret&page=1"), "csrf_token=%2A%2A%2A&page=1")

    def test_discovery_suggests_backend_api_from_video_response(self):
        request = {
            "url": "https://seller.tiktokshop.com/api/affiliate/video/list?page=1&page_size=20&csrf_token=secret",
            "method": "GET",
            "headers": {"accept": "application/json", "cookie": "sid=secret"},
        }
        response = {"url": request["url"], "status": 200, "mimeType": "application/json"}
        body = '{"data":{"list":[{"creator_username":"demo","video_link":"https://www.tiktok.com/@demo/video/700","publish_status":"published"}],"has_more":false}}'
        suggestion = suggest_backend_api(request, response, body, record_count=1, account_name="shop_a")
        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertEqual(suggestion.env["TK_BACKEND_ACCOUNT"], "shop_a")
        self.assertEqual(suggestion.env["TK_BACKEND_API_METHOD"], "GET")
        self.assertIn("csrf_token=%2A%2A%2A", suggestion.env["TK_BACKEND_API_URL"])
        self.assertNotIn("secret", suggestion.to_dict()["env"]["TK_BACKEND_API_URL"])
        self.assertIn("secret", suggestion.to_config().api_url)
        self.assertEqual(suggestion.to_config().page_size, 20)

    def test_network_monitor_parse_methods(self):
        self.assertEqual(parse_methods("get, post "), ("GET", "POST"))


if __name__ == "__main__":
    unittest.main()
