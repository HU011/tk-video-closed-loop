from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.db import db
from services.importer import import_video_rows
from tk_automation.browser.cdp_client import CDPClient
from tk_automation.collectors.completed_video_links import CompletedVideoLink, CompletedVideoLinkCollector


@dataclass(frozen=True)
class BackendApiCollectionConfig:
    api_url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: Any | None = None
    account_name: str = "tk_completed"
    cdp_host: str = "127.0.0.1"
    cdp_port: int = 9333
    page_url_contains: str = "tiktok"
    page_start: int = 1
    page_size: int = 50
    page_param: str = "page"
    page_size_param: str = "page_size"
    cursor_param: str = ""
    initial_cursor: str = ""
    next_cursor_fields: tuple[str, ...] = ("next_cursor", "nextCursor", "next_page_token", "nextPageToken")
    has_more_fields: tuple[str, ...] = ("has_more", "hasMore", "has_next", "hasNext")
    max_pages: int = 1
    request_timeout: int = 30
    stop_on_empty: bool = True

    @classmethod
    def from_env(cls) -> "BackendApiCollectionConfig":
        return cls(
            api_url=os.environ.get("TK_BACKEND_API_URL", ""),
            method=os.environ.get("TK_BACKEND_API_METHOD", "GET"),
            headers=parse_json_value(os.environ.get("TK_BACKEND_API_HEADERS"), default={}),
            body=parse_json_value(os.environ.get("TK_BACKEND_API_BODY"), default=None),
            account_name=os.environ.get("TK_BACKEND_ACCOUNT", "tk_completed"),
            cdp_host=os.environ.get("TK_CDP_HOST", "127.0.0.1"),
            cdp_port=int(os.environ.get("TK_CHROME_DEBUG_PORT", "9333")),
            page_url_contains=os.environ.get("TK_BACKEND_PAGE_URL_CONTAINS", "tiktok"),
            page_start=int(os.environ.get("TK_BACKEND_PAGE_START", "1")),
            page_size=int(os.environ.get("TK_BACKEND_PAGE_SIZE", "50")),
            page_param=os.environ.get("TK_BACKEND_PAGE_PARAM", "page"),
            page_size_param=os.environ.get("TK_BACKEND_PAGE_SIZE_PARAM", "page_size"),
            cursor_param=os.environ.get("TK_BACKEND_CURSOR_PARAM", ""),
            initial_cursor=os.environ.get("TK_BACKEND_INITIAL_CURSOR", ""),
            next_cursor_fields=parse_list_values(
                os.environ.get("TK_BACKEND_NEXT_CURSOR_FIELDS", "next_cursor,nextCursor,next_page_token,nextPageToken")
            ),
            has_more_fields=parse_list_values(os.environ.get("TK_BACKEND_HAS_MORE_FIELDS", "has_more,hasMore,has_next,hasNext")),
            max_pages=int(os.environ.get("TK_BACKEND_MAX_PAGES", "1")),
            request_timeout=int(os.environ.get("TK_BACKEND_REQUEST_TIMEOUT", "30")),
            stop_on_empty=parse_bool(os.environ.get("TK_BACKEND_STOP_ON_EMPTY", "true")),
        )


@dataclass(frozen=True)
class BackendApiPageResult:
    page: int
    status: int
    url: str
    record_count: int
    cursor: str = ""
    next_cursor: str = ""
    has_more: bool | None = None


@dataclass(frozen=True)
class BackendApiCollectionResult:
    records: list[CompletedVideoLink]
    pages: list[BackendApiPageResult]


class BackendApiCompletedVideoCollector:
    def __init__(self, config: BackendApiCollectionConfig) -> None:
        if not config.api_url:
            raise ValueError("TK backend API URL is required. Set TK_BACKEND_API_URL or pass --api-url.")
        self.config = config
        self.link_collector = CompletedVideoLinkCollector()

    def collect(self) -> BackendApiCollectionResult:
        records: list[CompletedVideoLink] = []
        pages: list[BackendApiPageResult] = []
        cursor = self.config.initial_cursor
        client = CDPClient.connect_to_page(
            host=self.config.cdp_host,
            port=self.config.cdp_port,
            url_contains=self.config.page_url_contains,
            timeout=self.config.request_timeout,
        )
        try:
            client.call("Runtime.enable", timeout=self.config.request_timeout)
            for page in range(self.config.page_start, self.config.page_start + self.config.max_pages):
                response = self._fetch_page(client, page, cursor)
                status = int(response.get("status") or 0)
                response_url = str(response.get("url") or self._request_url(page, cursor))
                if not response.get("ok"):
                    raise RuntimeError(f"TK backend request failed: HTTP {status} {response_url}")
                page_records = self.link_collector.collect_api_data(
                    response.get("data"),
                    account_name=self.config.account_name,
                    source=f"tk_backend_api:{response_url}",
                )
                records.extend(page_records)
                has_more = find_first_bool(response.get("data"), self.config.has_more_fields)
                next_cursor = str(find_first_value(response.get("data"), self.config.next_cursor_fields) or "")
                pages.append(
                    BackendApiPageResult(
                        page=page,
                        status=status,
                        url=response_url,
                        record_count=len(page_records),
                        cursor=cursor,
                        next_cursor=next_cursor,
                        has_more=has_more,
                    )
                )
                if self.config.stop_on_empty and not page_records:
                    break
                if self.config.cursor_param:
                    if has_more is False or not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor
        finally:
            client.close()
        return BackendApiCollectionResult(records=self.link_collector._dedupe(records), pages=pages)

    def import_to_db(self, records: list[CompletedVideoLink]) -> dict[str, int]:
        rows = [record.to_video_row() for record in self.link_collector._dedupe(records)]
        if not rows:
            return {"imported": 0}
        with db() as conn:
            return import_video_rows(conn, rows)

    def _fetch_page(self, client: CDPClient, page: int, cursor: str) -> dict[str, Any]:
        request = {
            "url": self._request_url(page, cursor),
            "method": self.config.method.upper(),
            "headers": self._request_headers(page, cursor),
            "body": self._request_body(page, cursor),
        }
        expression = build_fetch_expression(request)
        result = client.evaluate(expression, timeout=self.config.request_timeout)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected TK backend response: {result!r}")
        return result

    def _request_url(self, page: int, cursor: str = "") -> str:
        url = render_template(self.config.api_url, page=page, page_size=self.config.page_size, cursor=cursor)
        if self.config.method.upper() != "GET":
            return url
        query: dict[str, Any] = {}
        if self.config.page_param:
            query[self.config.page_param] = page
        if self.config.page_size_param:
            query[self.config.page_size_param] = self.config.page_size
        if self.config.cursor_param and cursor:
            query[self.config.cursor_param] = cursor
        return add_query_params(url, query)

    def _request_headers(self, page: int, cursor: str) -> dict[str, str]:
        headers = render_template(self.config.headers, page=page, page_size=self.config.page_size, cursor=cursor)
        if not isinstance(headers, dict):
            return {}
        return {str(key): str(value) for key, value in headers.items()}

    def _request_body(self, page: int, cursor: str) -> str | None:
        if self.config.method.upper() == "GET":
            return None
        body = render_template(self.config.body, page=page, page_size=self.config.page_size, cursor=cursor)
        if body is None:
            body = {}
        if isinstance(body, dict):
            if self.config.page_param and self.config.page_param not in body:
                body[self.config.page_param] = page
            if self.config.page_size_param and self.config.page_size_param not in body:
                body[self.config.page_size_param] = self.config.page_size
            if self.config.cursor_param and cursor and self.config.cursor_param not in body:
                body[self.config.cursor_param] = cursor
        if isinstance(body, (dict, list)):
            return json.dumps(body, ensure_ascii=False)
        return str(body)


def build_fetch_expression(request: dict[str, Any]) -> str:
    request_json = json.dumps(request, ensure_ascii=False)
    return f"""
(async () => {{
  const req = {request_json};
  const target = new URL(req.url, window.location.origin);
  const headers = req.headers || {{}};
  const options = {{
    method: req.method || "GET",
    credentials: "include",
    redirect: "follow",
    headers
  }};
  if (req.body !== null && req.body !== undefined) {{
    if (!Object.keys(headers).some((key) => key.toLowerCase() === "content-type")) {{
      headers["content-type"] = "application/json";
    }}
    options.body = req.body;
  }}
  const response = await fetch(target.toString(), options);
  const text = await response.text();
  let data = text;
  try {{
    data = JSON.parse(text);
  }} catch (error) {{}}
  return {{ ok: response.ok, status: response.status, url: response.url, data }};
}})()
"""


def add_query_params(url: str, params: dict[str, Any]) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        if key:
            query[str(key)] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def render_template(value: Any, page: int, page_size: int, cursor: str = "") -> Any:
    if isinstance(value, str):
        return value.replace("{page}", str(page)).replace("{page_size}", str(page_size)).replace("{cursor}", cursor)
    if isinstance(value, dict):
        return {render_template(key, page, page_size, cursor): render_template(item, page, page_size, cursor) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, page, page_size, cursor) for item in value]
    return value


def parse_list_values(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def find_first_value(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for item in value.values():
            found = find_first_value(item, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_first_value(item, keys)
            if found is not None:
                return found
    return None


def find_first_bool(value: Any, keys: tuple[str, ...]) -> bool | None:
    found = find_first_value(value, keys)
    if isinstance(found, bool):
        return found
    if found is None:
        return None
    if isinstance(found, (int, float)):
        return bool(found)
    lowered = str(found).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def parse_json_value(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
