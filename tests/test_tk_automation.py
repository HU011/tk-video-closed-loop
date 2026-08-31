import json
import unittest
from unittest.mock import patch

from tk_automation.collectors.completed_video_links import CompletedVideoLinkCollector
from tk_automation.collectors.backend_api import (
    BackendApiCollectionConfig,
    BackendApiCompletedVideoCollector,
    add_query_params,
    find_first_bool,
    find_first_value,
    render_template,
)
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

    def test_api_data_rejects_incomplete_publish_statuses(self):
        records = CompletedVideoLinkCollector().collect_api_data(
            {
                "list": [
                    {"creator_username": "demo", "video_link": "https://www.tiktok.com/@demo/video/501", "publish_status": "publishing"},
                    {"creator_username": "demo", "video_link": "https://www.tiktok.com/@demo/video/502", "publish_status": "unpublished"},
                    {"creator_username": "demo", "video_link": "https://www.tiktok.com/@demo/video/503", "publish_status": "not_published"},
                ]
            },
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

    def test_discovery_keeps_sensitive_custom_headers_only_in_runtime_config(self):
        request = {
            "url": "https://seller.tiktokshop.com/api/affiliate/video/list?page=1&page_size=20",
            "method": "POST",
            "headers": {
                "accept": "application/json",
                "content-type": "application/json",
                "cookie": "sid=secret",
                "x-csrf-token": "secret-token",
                "x-business-context": "seller-center",
                "sec-fetch-site": "same-origin",
            },
            "postData": '{"page":1,"page_size":20}',
        }
        response = {"url": request["url"], "status": 200, "mimeType": "application/json"}
        body = '{"data":{"list":[{"creator_username":"demo","video_link":"https://www.tiktok.com/@demo/video/704","publish_status":"published"}]}}'
        suggestion = suggest_backend_api(request, response, body, record_count=1, account_name="shop_a")
        self.assertIsNotNone(suggestion)
        assert suggestion is not None

        safe_headers = json.loads(suggestion.env["TK_BACKEND_API_HEADERS"])
        self.assertEqual(safe_headers["x-csrf-token"], "***")
        self.assertEqual(safe_headers["x-business-context"], "seller-center")
        self.assertNotIn("cookie", {key.lower(): value for key, value in safe_headers.items()})
        self.assertNotIn("sec-fetch-site", {key.lower(): value for key, value in safe_headers.items()})
        self.assertNotIn("secret-token", json.dumps(suggestion.to_dict(), ensure_ascii=False))

        runtime_headers = suggestion.to_config().headers
        self.assertEqual(runtime_headers["x-csrf-token"], "secret-token")
        self.assertEqual(runtime_headers["x-business-context"], "seller-center")
        self.assertNotIn("cookie", {key.lower(): value for key, value in runtime_headers.items()})

    def test_discovery_suggests_post_body_template(self):
        request = {
            "url": "https://seller.tiktokshop.com/api/affiliate/video/list",
            "method": "POST",
            "postData": '{"page":1,"page_size":20,"status":"published","csrf_token":"secret"}',
            "headers": {"content-type": "application/json"},
        }
        response = {"url": request["url"], "status": 200, "mimeType": "application/json"}
        body = '{"data":{"list":[{"creator_username":"demo","video_link":"https://www.tiktok.com/@demo/video/701","publish_status":"published"}],"has_more":false}}'
        suggestion = suggest_backend_api(request, response, body, record_count=1, account_name="shop_a")
        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertEqual(suggestion.to_config().body["page"], "{page}")
        self.assertEqual(suggestion.to_config().body["page_size"], "{page_size}")
        self.assertEqual(suggestion.env["TK_BACKEND_API_BODY"], '{"page": "{page}", "page_size": "{page_size}", "status": "published", "csrf_token": "***"}')

    def test_discovery_suggests_form_post_body_template(self):
        request = {
            "url": "https://seller.tiktokshop.com/api/affiliate/video/list",
            "method": "POST",
            "postData": "page=1&page_size=20&status=published&csrf_token=secret",
            "headers": {"content-type": "application/x-www-form-urlencoded"},
        }
        response = {"url": request["url"], "status": 200, "mimeType": "application/json"}
        body = '{"data":{"list":[{"creator_username":"demo","video_link":"https://www.tiktok.com/@demo/video/703","publish_status":"published"}],"has_more":false}}'
        suggestion = suggest_backend_api(request, response, body, record_count=1, account_name="shop_a")
        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertEqual(suggestion.to_config().body, "page={page}&page_size={page_size}&status=published&csrf_token=secret")
        self.assertEqual(suggestion.env["TK_BACKEND_API_BODY"], "page={page}&page_size={page_size}&status=published&csrf_token=%2A%2A%2A")
        self.assertEqual(suggestion.to_config().page_size, 20)

    def test_backend_form_body_uses_urlencoded_payload(self):
        config = BackendApiCollectionConfig(
            api_url="https://seller.tiktokshop.com/api/videos",
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded"},
            body={"page": "{page}", "page_size": "{page_size}", "status": "published"},
            page_size=20,
        )
        body = BackendApiCompletedVideoCollector(config)._request_body(page=3, cursor="")
        self.assertEqual(body, "page=3&page_size=20&status=published")

    def test_backend_page_mode_stops_on_has_more_false(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def call(self, *_args, **_kwargs):
                return {}

            def evaluate(self, *_args, **_kwargs):
                self.calls += 1
                return {
                    "ok": True,
                    "status": 200,
                    "url": f"https://seller.tiktokshop.com/api/videos?page={self.calls}",
                    "data": {
                        "list": [
                            {
                                "creator_username": "demo",
                                "video_link": "https://www.tiktok.com/@demo/video/702",
                                "publish_status": "published",
                            }
                        ],
                        "has_more": False,
                    },
                }

            def close(self):
                return None

        fake_client = FakeClient()
        config = BackendApiCollectionConfig(api_url="https://seller.tiktokshop.com/api/videos", max_pages=5)
        with patch("tk_automation.collectors.backend_api.CDPClient.connect_to_page", return_value=fake_client):
            result = BackendApiCompletedVideoCollector(config).collect()
        self.assertEqual(fake_client.calls, 1)
        self.assertEqual(len(result.records), 1)

    def test_network_monitor_parse_methods(self):
        self.assertEqual(parse_methods("get, post "), ("GET", "POST"))


if __name__ == "__main__":
    unittest.main()
