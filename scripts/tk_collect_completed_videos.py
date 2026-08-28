from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
if str(ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(ROOT_FOR_IMPORTS))

from core.db import init_db
from tk_automation.auth.email_code import EmailCodeConfig, EmailCodeReader
from tk_automation.browser.chrome_launcher import ChromeLaunchConfig, ChromeLauncher
from tk_automation.collectors.backend_api import (
    BackendApiCollectionConfig,
    BackendApiCompletedVideoCollector,
    parse_json_value,
)
from tk_automation.collectors.network_monitor import NetworkMonitorConfig, TKNetworkMonitor, parse_methods


def main() -> int:
    parser = argparse.ArgumentParser(description="独立 TK 后台已完成视频链接采集工具。")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chrome-command", help="输出带独立本地登录目录的 Chrome 启动命令。")
    sub.add_parser("email-code", help="从 IMAP 邮箱读取最新 TK 登录验证码。")

    wait_parser = sub.add_parser("wait-email-code", help="轮询邮箱，直到读取到 TK 登录验证码。")
    wait_parser.add_argument("--timeout", type=int, default=180)
    wait_parser.add_argument("--interval", type=int, default=5)

    listen_network = sub.add_parser("listen-network", help="监听已登录 Chrome 的 TK 后台 Network 请求，提取已完成视频链接。")
    listen_network.add_argument("--account", default="", help="写入数据库时使用的账号标签。")
    listen_network.add_argument("--cdp-host", default="", help="Chrome DevTools 主机。")
    listen_network.add_argument("--cdp-port", type=int, default=None, help="Chrome DevTools 端口。")
    listen_network.add_argument("--page-url-contains", default="", help="选择 URL 包含该文本的已登录 Chrome 页面。")
    listen_network.add_argument("--request-url-contains", default="", help="只监听 URL 包含该文本的后台请求。")
    listen_network.add_argument("--methods", default="", help="请求方法过滤，例如 GET,POST。")
    listen_network.add_argument("--timeout", type=int, default=None, help="监听秒数。")
    listen_network.add_argument("--max-responses", type=int, default=None, help="最多处理多少个匹配响应。")
    listen_network.add_argument("--no-response-body", action="store_true", help="只打印请求细节，不解析响应正文。")
    listen_network.add_argument("--import-db", action="store_true")

    collect_auto = sub.add_parser("collect-auto", help="监听 TK 后台 Network，自动发现接口并翻页采集已完成视频链接。")
    collect_auto.add_argument("--account", default="", help="写入数据库时使用的账号标签。")
    collect_auto.add_argument("--cdp-host", default="", help="Chrome DevTools 主机。")
    collect_auto.add_argument("--cdp-port", type=int, default=None, help="Chrome DevTools 端口。")
    collect_auto.add_argument("--page-url-contains", default="", help="选择 URL 包含该文本的已登录 Chrome 页面。")
    collect_auto.add_argument("--request-url-contains", default="", help="只监听 URL 包含该文本的后台请求。")
    collect_auto.add_argument("--methods", default="", help="请求方法过滤，例如 GET,POST。")
    collect_auto.add_argument("--listen-timeout", type=int, default=None, help="监听秒数。")
    collect_auto.add_argument("--max-responses", type=int, default=None, help="最多处理多少个匹配响应。")
    collect_auto.add_argument("--max-pages", type=int, default=None, help="发现接口后继续采集的最大页数。")
    collect_auto.add_argument("--request-timeout", type=int, default=None, help="后台 API 请求超时秒数。")
    collect_auto.add_argument("--no-stop-on-empty", action="store_true")
    collect_auto.add_argument("--import-db", action="store_true")

    collect_api = sub.add_parser("collect-api", help="通过已登录 Chrome 请求 TK 后台 API，采集已完成视频链接。")
    collect_api.add_argument("--api-url", default="", help="TK 后台接口路径或完整 URL；默认读取 TK_BACKEND_API_URL。")
    collect_api.add_argument("--method", default="", help="GET 或 POST；默认读取 TK_BACKEND_API_METHOD。")
    collect_api.add_argument("--headers", default=None, help="JSON 请求头，例如 '{\"x-foo\":\"bar\"}'。")
    collect_api.add_argument("--body", default=None, help="JSON 请求体或原始字符串，支持 {page} 和 {page_size}。")
    collect_api.add_argument("--account", default="", help="写入数据库时使用的账号标签。")
    collect_api.add_argument("--cdp-host", default="", help="Chrome DevTools 主机。")
    collect_api.add_argument("--cdp-port", type=int, default=None, help="Chrome DevTools 端口。")
    collect_api.add_argument("--page-url-contains", default="", help="选择 URL 包含该文本的已登录 Chrome 页面。")
    collect_api.add_argument("--page-start", type=int, default=None)
    collect_api.add_argument("--page-size", type=int, default=None)
    collect_api.add_argument("--page-param", default=None)
    collect_api.add_argument("--page-size-param", default=None)
    collect_api.add_argument("--cursor-param", default=None)
    collect_api.add_argument("--initial-cursor", default=None)
    collect_api.add_argument("--next-cursor-fields", default=None, help="响应里的下一页游标字段，逗号分隔。")
    collect_api.add_argument("--has-more-fields", default=None, help="响应里的是否还有下一页字段，逗号分隔。")
    collect_api.add_argument("--max-pages", type=int, default=None)
    collect_api.add_argument("--request-timeout", type=int, default=None)
    collect_api.add_argument("--no-stop-on-empty", action="store_true")
    collect_api.add_argument("--import-db", action="store_true")

    args = parser.parse_args()

    if args.command == "chrome-command":
        command = ChromeLauncher(ChromeLaunchConfig.from_env()).command()
        print(json.dumps({"command": command}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "email-code":
        code = EmailCodeReader(EmailCodeConfig.from_env()).fetch_latest_code()
        print(json.dumps({"code": code}, ensure_ascii=False))
        return 0 if code else 1
    if args.command == "wait-email-code":
        code = EmailCodeReader(EmailCodeConfig.from_env()).wait_for_code(args.timeout, args.interval)
        print(json.dumps({"code": code}, ensure_ascii=False))
        return 0 if code else 1

    if args.command == "listen-network":
        if args.import_db:
            init_db()
        env_config = NetworkMonitorConfig.from_env()
        config = replace(
            env_config,
            account_name=args.account or env_config.account_name,
            cdp_host=args.cdp_host or env_config.cdp_host,
            cdp_port=args.cdp_port if args.cdp_port is not None else env_config.cdp_port,
            page_url_contains=args.page_url_contains or env_config.page_url_contains,
            request_url_contains=args.request_url_contains or env_config.request_url_contains,
            methods=parse_methods(args.methods) if args.methods else env_config.methods,
            timeout=args.timeout if args.timeout is not None else env_config.timeout,
            max_responses=args.max_responses if args.max_responses is not None else env_config.max_responses,
            import_response_body=False if args.no_response_body else env_config.import_response_body,
        )
        monitor = TKNetworkMonitor(config)
        result_data = monitor.listen()
        result = {
            "captured_count": len(result_data.captured_requests),
            "count": len(result_data.records),
            "requests": [request.to_dict() for request in result_data.captured_requests],
            "suggestions": [suggestion.to_dict() for suggestion in result_data.suggestions],
            "items": [record.to_video_row() for record in result_data.records],
        }
        if args.import_db:
            result["import"] = monitor.import_to_db(result_data.records)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "collect-auto":
        if args.import_db:
            init_db()
        env_config = NetworkMonitorConfig.from_env()
        monitor_config = replace(
            env_config,
            account_name=args.account or env_config.account_name,
            cdp_host=args.cdp_host or env_config.cdp_host,
            cdp_port=args.cdp_port if args.cdp_port is not None else env_config.cdp_port,
            page_url_contains=args.page_url_contains or env_config.page_url_contains,
            request_url_contains=args.request_url_contains or env_config.request_url_contains,
            methods=parse_methods(args.methods) if args.methods else env_config.methods,
            timeout=args.listen_timeout if args.listen_timeout is not None else env_config.timeout,
            max_responses=args.max_responses if args.max_responses is not None else env_config.max_responses,
            import_response_body=True,
        )
        monitor = TKNetworkMonitor(monitor_config)
        monitor_result = monitor.listen()
        if not monitor_result.suggestions:
            print(
                json.dumps(
                    {
                        "error": "没有从 Network 响应中发现可复用的已完成视频接口",
                        "captured_count": len(monitor_result.captured_requests),
                        "requests": [request.to_dict() for request in monitor_result.captured_requests],
                        "items": [record.to_video_row() for record in monitor_result.records],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        suggestion = monitor_result.suggestions[0]
        api_config = suggestion.to_config(max_pages=args.max_pages, account_name=args.account or monitor_config.account_name)
        api_config = replace(
            api_config,
            cdp_host=monitor_config.cdp_host,
            cdp_port=monitor_config.cdp_port,
            page_url_contains=monitor_config.page_url_contains,
            request_timeout=args.request_timeout if args.request_timeout is not None else api_config.request_timeout,
            stop_on_empty=False if args.no_stop_on_empty else api_config.stop_on_empty,
        )
        collector = BackendApiCompletedVideoCollector(api_config)
        collected = collector.collect()
        result = {
            "discovered_api": suggestion.to_dict(),
            "listen": {
                "captured_count": len(monitor_result.captured_requests),
                "count": len(monitor_result.records),
                "requests": [request.to_dict() for request in monitor_result.captured_requests],
            },
            "count": len(collected.records),
            "pages": [page.__dict__ for page in collected.pages],
            "items": [record.to_video_row() for record in collected.records],
        }
        if args.import_db:
            result["import"] = collector.import_to_db(collected.records)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "collect-api":
        if args.import_db:
            init_db()
        env_config = BackendApiCollectionConfig.from_env()
        config = replace(
            env_config,
            api_url=args.api_url or env_config.api_url,
            method=args.method or env_config.method,
            headers=parse_json_value(args.headers, default=env_config.headers) if args.headers is not None else env_config.headers,
            body=parse_json_value(args.body, default=env_config.body) if args.body is not None else env_config.body,
            account_name=args.account or env_config.account_name,
            cdp_host=args.cdp_host or env_config.cdp_host,
            cdp_port=args.cdp_port if args.cdp_port is not None else env_config.cdp_port,
            page_url_contains=args.page_url_contains or env_config.page_url_contains,
            page_start=args.page_start if args.page_start is not None else env_config.page_start,
            page_size=args.page_size if args.page_size is not None else env_config.page_size,
            page_param=args.page_param if args.page_param is not None else env_config.page_param,
            page_size_param=args.page_size_param if args.page_size_param is not None else env_config.page_size_param,
            cursor_param=args.cursor_param if args.cursor_param is not None else env_config.cursor_param,
            initial_cursor=args.initial_cursor if args.initial_cursor is not None else env_config.initial_cursor,
            next_cursor_fields=tuple(item.strip() for item in args.next_cursor_fields.split(",") if item.strip())
            if args.next_cursor_fields is not None
            else env_config.next_cursor_fields,
            has_more_fields=tuple(item.strip() for item in args.has_more_fields.split(",") if item.strip())
            if args.has_more_fields is not None
            else env_config.has_more_fields,
            max_pages=args.max_pages if args.max_pages is not None else env_config.max_pages,
            request_timeout=args.request_timeout if args.request_timeout is not None else env_config.request_timeout,
            stop_on_empty=False if args.no_stop_on_empty else env_config.stop_on_empty,
        )
        collector = BackendApiCompletedVideoCollector(config)
        collected = collector.collect()
        result = {
            "count": len(collected.records),
            "pages": [page.__dict__ for page in collected.pages],
            "items": [record.to_video_row() for record in collected.records],
        }
        if args.import_db:
            result["import"] = collector.import_to_db(collected.records)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
