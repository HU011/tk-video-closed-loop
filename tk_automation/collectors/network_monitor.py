from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from core.db import db
from services.importer import import_video_rows
from tk_automation.browser.cdp_client import CDPClient, CDPError
from tk_automation.collectors.backend_api import parse_bool
from tk_automation.collectors.completed_video_links import CompletedVideoLink, CompletedVideoLinkCollector


SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-csrf-token",
    "x-tt-token",
    "x-tt-csrf-token",
}


@dataclass(frozen=True)
class NetworkMonitorConfig:
    account_name: str = "tk_completed"
    cdp_host: str = "127.0.0.1"
    cdp_port: int = 9333
    page_url_contains: str = "tiktok"
    request_url_contains: str = ""
    methods: tuple[str, ...] = ("GET", "POST")
    timeout: int = 120
    max_responses: int = 20
    import_response_body: bool = True

    @classmethod
    def from_env(cls) -> "NetworkMonitorConfig":
        return cls(
            account_name=os.environ.get("TK_MONITOR_ACCOUNT", os.environ.get("TK_BACKEND_ACCOUNT", "tk_completed")),
            cdp_host=os.environ.get("TK_CDP_HOST", "127.0.0.1"),
            cdp_port=int(os.environ.get("TK_CHROME_DEBUG_PORT", "9333")),
            page_url_contains=os.environ.get("TK_MONITOR_PAGE_URL_CONTAINS", "tiktok"),
            request_url_contains=os.environ.get("TK_MONITOR_URL_CONTAINS", ""),
            methods=parse_methods(os.environ.get("TK_MONITOR_METHODS", "GET,POST")),
            timeout=int(os.environ.get("TK_MONITOR_TIMEOUT", "120")),
            max_responses=int(os.environ.get("TK_MONITOR_MAX_RESPONSES", "20")),
            import_response_body=parse_bool(os.environ.get("TK_MONITOR_IMPORT_RESPONSE_BODY", "true")),
        )


@dataclass(frozen=True)
class CapturedRequest:
    request_id: str
    url: str
    method: str
    query: dict[str, str]
    headers: dict[str, str]
    post_data: str
    status: int
    mime_type: str
    record_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "url": self.url,
            "method": self.method,
            "query": self.query,
            "headers": self.headers,
            "post_data": self.post_data,
            "status": self.status,
            "mime_type": self.mime_type,
            "record_count": self.record_count,
        }


@dataclass(frozen=True)
class NetworkMonitorResult:
    captured_requests: list[CapturedRequest]
    records: list[CompletedVideoLink]


class TKNetworkMonitor:
    def __init__(self, config: NetworkMonitorConfig) -> None:
        self.config = config
        self.link_collector = CompletedVideoLinkCollector()

    def listen(self) -> NetworkMonitorResult:
        client = CDPClient.connect_to_page(
            host=self.config.cdp_host,
            port=self.config.cdp_port,
            url_contains=self.config.page_url_contains,
            timeout=min(self.config.timeout, 30),
        )
        requests: dict[str, dict[str, Any]] = {}
        responses: dict[str, dict[str, Any]] = {}
        captured: list[CapturedRequest] = []
        records: list[CompletedVideoLink] = []
        deadline = time.monotonic() + self.config.timeout
        try:
            client.call("Network.enable", timeout=10)
            while time.monotonic() < deadline and len(captured) < self.config.max_responses:
                try:
                    event = client.next_message(timeout=max(1, int(deadline - time.monotonic())))
                except TimeoutError:
                    break
                method = event.get("method")
                params = event.get("params") or {}
                request_id = str(params.get("requestId") or "")
                if method == "Network.requestWillBeSent":
                    request = params.get("request") or {}
                    if self._matches_request(request):
                        requests[request_id] = request
                elif method == "Network.responseReceived" and request_id in requests:
                    responses[request_id] = params.get("response") or {}
                elif method == "Network.loadingFinished" and request_id in requests:
                    response = responses.get(request_id, {})
                    body = self._get_response_body(client, request_id) if self.config.import_response_body else None
                    page_records = self._records_from_body(body, response)
                    records.extend(page_records)
                    captured.append(self._captured_request(request_id, requests[request_id], response, len(page_records)))
        finally:
            client.close()
        return NetworkMonitorResult(captured_requests=captured, records=self.link_collector._dedupe(records))

    def import_to_db(self, records: list[CompletedVideoLink]) -> dict[str, int]:
        rows = [record.to_video_row() for record in self.link_collector._dedupe(records)]
        if not rows:
            return {"imported": 0}
        with db() as conn:
            return import_video_rows(conn, rows)

    def _matches_request(self, request: dict[str, Any]) -> bool:
        url = str(request.get("url") or "")
        method = str(request.get("method") or "").upper()
        if self.config.methods and method not in self.config.methods:
            return False
        if self.config.request_url_contains and self.config.request_url_contains.lower() not in url.lower():
            return False
        return bool(url.startswith("http://") or url.startswith("https://"))

    def _get_response_body(self, client: CDPClient, request_id: str) -> str:
        try:
            result = client.call("Network.getResponseBody", {"requestId": request_id}, timeout=10)
        except (CDPError, TimeoutError):
            return ""
        body = str(result.get("body") or "")
        if result.get("base64Encoded"):
            try:
                return base64.b64decode(body).decode("utf-8", errors="replace")
            except ValueError:
                return ""
        return body

    def _records_from_body(self, body: str | None, response: dict[str, Any]) -> list[CompletedVideoLink]:
        if not body:
            return []
        source = f"tk_network:{response.get('url') or ''}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self.link_collector.collect_text(body, account_name=self.config.account_name, source=source)
        return self.link_collector.collect_api_data(data, account_name=self.config.account_name, source=source)

    def _captured_request(self, request_id: str, request: dict[str, Any], response: dict[str, Any], record_count: int) -> CapturedRequest:
        url = str(request.get("url") or "")
        return CapturedRequest(
            request_id=request_id,
            url=url,
            method=str(request.get("method") or ""),
            query=dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)),
            headers=sanitize_headers(request.get("headers") or {}),
            post_data=str(request.get("postData") or ""),
            status=int(response.get("status") or 0),
            mime_type=str(response.get("mimeType") or ""),
            record_count=record_count,
        )


def parse_methods(raw: str) -> tuple[str, ...]:
    methods = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return tuple(methods)


def sanitize_headers(headers: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        header_name = str(key)
        if header_name.lower() in SENSITIVE_HEADER_NAMES:
            result[header_name] = "***"
        else:
            result[header_name] = str(value)
    return result
