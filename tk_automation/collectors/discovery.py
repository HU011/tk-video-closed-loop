from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Any

from tk_automation.collectors.backend_api import BackendApiCollectionConfig, parse_json_value


PAGE_KEYS = ("page", "pageNo", "page_no", "pageNum", "page_num", "current", "currentPage", "pageIndex", "page_index")
PAGE_SIZE_KEYS = ("page_size", "pageSize", "page_size", "size", "limit", "per_page", "perPage", "count")
CURSOR_KEYS = ("cursor", "next_cursor", "nextCursor", "page_token", "pageToken", "search_after", "searchAfter")
HAS_MORE_KEYS = ("has_more", "hasMore", "has_next", "hasNext", "more", "is_more", "isMore")
NEXT_CURSOR_KEYS = ("next_cursor", "nextCursor", "next_page_token", "nextPageToken", "page_token", "pageToken")
SENSITIVE_NAMES = ("token", "auth", "cookie", "csrf", "secret", "password", "session")
BUSINESS_URL_MARKERS = ("video", "content", "creator", "affiliate", "product", "item", "publish", "performance")
VIDEO_DATA_KEYS = {
    "video_url",
    "video_link",
    "share_url",
    "video_id",
    "item_id",
    "aweme_id",
    "creator_username",
    "username",
    "play_count",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
    "order_count",
    "gmv",
    "publish_status",
    "video_status",
}


@dataclass(frozen=True)
class DiscoveredBackendApi:
    score: int
    reasons: list[str]
    env: dict[str, str]
    runtime_env: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reasons": self.reasons,
            "env": self.env,
            "collect_command": ".\\venv\\Scripts\\python.exe scripts\\tk_collect_completed_videos.py collect-api --import-db",
        }

    def to_config(self, max_pages: int | None = None, account_name: str = "") -> BackendApiCollectionConfig:
        env = self.runtime_env or self.env
        return BackendApiCollectionConfig(
            api_url=env["TK_BACKEND_API_URL"],
            method=env.get("TK_BACKEND_API_METHOD", "GET"),
            headers=parse_json_value(env.get("TK_BACKEND_API_HEADERS"), default={}),
            body=parse_json_value(env.get("TK_BACKEND_API_BODY"), default=None),
            account_name=account_name or env.get("TK_BACKEND_ACCOUNT", "tk_completed"),
            page_size=_int_or_default(env.get("TK_BACKEND_PAGE_SIZE"), 50),
            page_param=env.get("TK_BACKEND_PAGE_PARAM", "page"),
            page_size_param=env.get("TK_BACKEND_PAGE_SIZE_PARAM", "page_size"),
            cursor_param=env.get("TK_BACKEND_CURSOR_PARAM", ""),
            next_cursor_fields=tuple(env.get("TK_BACKEND_NEXT_CURSOR_FIELDS", ",".join(NEXT_CURSOR_KEYS)).split(",")),
            has_more_fields=tuple(env.get("TK_BACKEND_HAS_MORE_FIELDS", ",".join(HAS_MORE_KEYS)).split(",")),
            max_pages=max_pages if max_pages is not None else _int_or_default(env.get("TK_BACKEND_MAX_PAGES"), 1),
        )


def suggest_backend_api(
    request: dict[str, Any],
    response: dict[str, Any],
    body: str | None,
    record_count: int,
    account_name: str,
) -> DiscoveredBackendApi | None:
    url = str(response.get("url") or request.get("url") or "")
    method = str(request.get("method") or "GET").upper()
    status = int(response.get("status") or 0)
    mime_type = str(response.get("mimeType") or "").lower()
    data = _json_or_none(body)
    keys = set(_walk_keys(data)) if data is not None else set()

    score = 0
    reasons: list[str] = []
    if status == 200:
        score += 10
        reasons.append("HTTP 200")
    if "json" in mime_type or data is not None:
        score += 15
        reasons.append("响应是 JSON")
    if record_count:
        score += min(50, 20 + record_count * 3)
        reasons.append(f"已提取 {record_count} 条视频记录")
    matched_video_keys = sorted(keys & VIDEO_DATA_KEYS)
    if matched_video_keys:
        score += min(25, len(matched_video_keys) * 3)
        reasons.append("包含视频/达人/指标字段: " + ", ".join(matched_video_keys[:8]))
    if any(marker in url.lower() for marker in BUSINESS_URL_MARKERS):
        score += 10
        reasons.append("URL 命中视频/达人/商品相关关键词")
    if keys & set(HAS_MORE_KEYS + NEXT_CURSOR_KEYS):
        score += 8
        reasons.append("响应包含分页游标或 has_more 字段")

    if score < 25:
        return None

    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True))
    raw_headers = request.get("headers") or {}
    post_data = str(request.get("postData") or "")
    content_type = _header_value(raw_headers, "content-type")
    parsed_body, body_format = _parse_request_body(post_data, content_type)
    page_param = _first_existing_key(query, PAGE_KEYS) or _first_existing_key(parsed_body, PAGE_KEYS) or "page"
    page_size_param = _first_existing_key(query, PAGE_SIZE_KEYS) or _first_existing_key(parsed_body, PAGE_SIZE_KEYS) or "page_size"
    cursor_param = _first_existing_key(query, CURSOR_KEYS) or _first_existing_key(parsed_body, CURSOR_KEYS) or ""
    api_url = _request_url_without_pagination(url, method, page_param, page_size_param, cursor_param, sanitize=False)
    safe_api_url = _request_url_without_pagination(url, method, page_param, page_size_param, cursor_param, sanitize=True)
    headers = _replay_headers(raw_headers)
    body_template = _request_body_template(parsed_body, body_format, page_param, page_size_param, cursor_param, sanitize=False) if method != "GET" else ""
    safe_body_template = _request_body_template(parsed_body, body_format, page_param, page_size_param, cursor_param, sanitize=True) if method != "GET" else ""
    page_size = _first_existing_value(query, PAGE_SIZE_KEYS) or _first_existing_value(parsed_body, PAGE_SIZE_KEYS) or "50"

    env = {
        "TK_BACKEND_API_URL": safe_api_url,
        "TK_BACKEND_API_METHOD": method,
        "TK_BACKEND_API_HEADERS": json.dumps(headers, ensure_ascii=False),
        "TK_BACKEND_API_BODY": _serialize_body_env(safe_body_template),
        "TK_BACKEND_ACCOUNT": account_name or "tk_completed",
        "TK_BACKEND_PAGE_SIZE": str(page_size),
        "TK_BACKEND_PAGE_PARAM": page_param,
        "TK_BACKEND_PAGE_SIZE_PARAM": page_size_param,
        "TK_BACKEND_CURSOR_PARAM": cursor_param,
        "TK_BACKEND_NEXT_CURSOR_FIELDS": ",".join(NEXT_CURSOR_KEYS),
        "TK_BACKEND_HAS_MORE_FIELDS": ",".join(HAS_MORE_KEYS),
        "TK_BACKEND_MAX_PAGES": "10",
    }
    runtime_env = {
        **env,
        "TK_BACKEND_API_URL": api_url,
        "TK_BACKEND_API_BODY": _serialize_body_env(body_template),
    }
    return DiscoveredBackendApi(score=score, reasons=reasons, env=env, runtime_env=runtime_env)


def _json_or_none(raw: str | None) -> Any | None:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _parse_request_body(raw: str, content_type: str) -> tuple[Any | None, str]:
    parsed_json = _json_or_none(raw)
    if parsed_json is not None:
        return parsed_json, "json"
    if _looks_like_form_body(raw, content_type):
        parsed_form = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
        if parsed_form:
            return parsed_form, "form"
    if raw:
        return raw, "raw"
    return None, "none"


def _looks_like_form_body(raw: str, content_type: str) -> bool:
    lowered = content_type.lower()
    return "application/x-www-form-urlencoded" in lowered or ("=" in raw and "&" in raw)


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def _first_existing_key(value: Any, candidates: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        for key in candidates:
            if key in value:
                return key
        for child in value.values():
            found = _first_existing_key(child, candidates)
            if found:
                return found
    return ""


def _first_existing_value(value: Any, candidates: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in candidates:
            if key in value and value[key] not in (None, ""):
                return value[key]
        for child in value.values():
            found = _first_existing_value(child, candidates)
            if found not in (None, ""):
                return found
    return None


def _request_url_without_pagination(
    url: str,
    method: str,
    page_param: str,
    page_size_param: str,
    cursor_param: str,
    sanitize: bool,
) -> str:
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    if method == "GET":
        for key in (page_param, page_size_param, cursor_param):
            if key:
                query.pop(key, None)
    clean_query = {key: ("***" if sanitize and _is_sensitive_name(key) else value) for key, value in query.items()}
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(clean_query), parts.fragment))


def _replay_headers(headers: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    browser_headers = {"accept", "content-type", "x-requested-with"}
    for key, value in headers.items():
        name = str(key)
        lowered = name.lower()
        if lowered not in browser_headers or _is_sensitive_name(lowered):
            continue
        result[name] = str(value)
    return result


def _header_value(headers: dict[str, Any], wanted: str) -> str:
    wanted_lower = wanted.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted_lower:
            return str(value)
    return ""


def _request_body_template(
    value: Any,
    body_format: str,
    page_param: str,
    page_size_param: str,
    cursor_param: str,
    sanitize: bool,
) -> Any:
    templated = _body_template(value, page_param, page_size_param, cursor_param, sanitize)
    if body_format == "form" and isinstance(templated, dict):
        return _urlencode_template({str(key): str(item) for key, item in templated.items()})
    return templated


def _serialize_body_env(value: Any) -> str:
    if value in ("", None):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _urlencode_template(values: dict[str, str]) -> str:
    encoded = urllib.parse.urlencode(values)
    return (
        encoded.replace("%7Bpage%7D", "{page}")
        .replace("%7Bpage_size%7D", "{page_size}")
        .replace("%7Bcursor%7D", "{cursor}")
    )


def _body_template(value: Any, page_param: str, page_size_param: str, cursor_param: str, sanitize: bool) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if sanitize and _is_sensitive_name(str(key)):
                result[key] = "***"
            elif key == page_param:
                result[key] = "{page}"
            elif key == page_size_param:
                result[key] = "{page_size}"
            elif cursor_param and key == cursor_param:
                result[key] = "{cursor}"
            else:
                result[key] = _body_template(child, page_param, page_size_param, cursor_param, sanitize)
        return result
    if isinstance(value, list):
        return [_body_template(item, page_param, page_size_param, cursor_param, sanitize) for item in value]
    return value


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in SENSITIVE_NAMES)
