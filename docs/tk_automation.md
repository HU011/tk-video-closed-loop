# TK 后台自动化采集模块

`tk_automation/` 是独立模块，不集成到 Web 页面。它用于辅助登录 TK 后台、读取邮箱验证码、监听真实 Network 请求、复用已登录页面主动请求后台 API，并把已完成视频链接导入当前项目数据库。

TK 后台采集只有两条主线：

1. 监听请求：你在已登录 TK 后台打开“已完成/已发布视频”相关页面并翻页，程序监听 Network，记录真实接口的 `url`、`method`、`headers`、`body`、分页参数和返回结构，并从 response 中提取视频链接。
2. 主动请求：确认接口后，程序复用已登录 Chrome 页面里的 Cookie/session，在页面上下文中执行 `fetch`，分页请求已完成视频列表并入库。

## 模块结构

```text
tk_automation/
├─ auth/
│  └─ email_code.py              # IMAP 邮箱验证码读取
├─ browser/
│  ├─ chrome_launcher.py         # 独立 Chrome 登录配置和启动命令
│  └─ cdp_client.py              # Chrome DevTools Protocol 连接
├─ collectors/
│  ├─ network_monitor.py         # 监听 TK 后台真实 Network 请求
│  ├─ backend_api.py             # 已登录页面上下文主动请求 TK 后台 API
│  └─ completed_video_links.py   # 视频链接解析、完成状态过滤和入库
├─ parsers/
│  └─ video_links.py             # TikTok 视频链接解析
└─ storage/
```

## 登录验证码

在 `.env` 中配置：

```env
TK_EMAIL_HOST=imap.example.com
TK_EMAIL_PORT=993
TK_EMAIL_USER=your-email@example.com
TK_EMAIL_PASSWORD=your-email-password-or-app-password
TK_EMAIL_MAILBOX=INBOX
TK_EMAIL_SENDER_FILTER=tiktok
TK_EMAIL_SUBJECT_FILTER=code
TK_EMAIL_CODE_REGEX=\b(\d{4,8})\b
```

读取或等待验证码：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py wait-email-code --timeout 180 --interval 5
```

## 启动登录浏览器

输出独立 Chrome 登录命令：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py chrome-command
```

复制输出里的命令并运行，然后登录 TK 后台。浏览器用户数据默认放在：

```text
runtime/chrome_profile
```

该目录不会提交到仓库。

## 方式一：监听请求

先启动监听：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py listen-network --request-url-contains video --timeout 120 --max-responses 20
```

然后在已登录的 TK 后台页面里手动进入已完成视频、达人带货视频、发布完成视频等列表页面，并翻页或筛选。程序会输出匹配请求的细节：

```json
{
  "url": "https://.../completed/video/list?...",
  "method": "POST",
  "query": {
    "page": "1",
    "page_size": "50"
  },
  "headers": {
    "content-type": "application/json",
    "cookie": "***"
  },
  "post_data": "{\"page\":1,\"page_size\":50}",
  "status": 200,
  "record_count": 12
}
```

`headers` 会默认脱敏 `cookie`、`authorization`、`x-csrf-token` 等敏感字段。监听模式的用途是确认真实接口、请求方法、分页字段、请求体和返回结构。

需要重点确认这些内容：

- `url`：已完成视频列表接口地址。
- `method`：GET 或 POST。
- `headers`：必要请求头，敏感值不要写进仓库。
- `query` / `post_data`：分页参数、筛选条件、达人/商品/任务状态参数。
- 返回结构：视频链接字段、播放/点赞/订单等指标字段。
- 翻页结束：空列表、`has_more=false`、`has_next=false`、没有 `next_cursor` 或下一页游标不再变化。

监听并直接导入数据库：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py listen-network --request-url-contains video --timeout 120 --import-db
```

## 方式二：主动请求

确认真实接口后，把接口配置到 `.env`：

```env
TK_CDP_HOST=127.0.0.1
TK_CHROME_DEBUG_PORT=9333
TK_BACKEND_PAGE_URL_CONTAINS=tiktok
TK_BACKEND_API_URL=/your/completed/video/list/api
TK_BACKEND_API_METHOD=GET
TK_BACKEND_API_HEADERS={}
TK_BACKEND_API_BODY=
TK_BACKEND_ACCOUNT=shop_account_a
TK_BACKEND_PAGE_START=1
TK_BACKEND_PAGE_SIZE=50
TK_BACKEND_PAGE_PARAM=page
TK_BACKEND_PAGE_SIZE_PARAM=page_size
TK_BACKEND_CURSOR_PARAM=
TK_BACKEND_INITIAL_CURSOR=
TK_BACKEND_NEXT_CURSOR_FIELDS=next_cursor,nextCursor,next_page_token,nextPageToken
TK_BACKEND_HAS_MORE_FIELDS=has_more,hasMore,has_next,hasNext
TK_BACKEND_MAX_PAGES=10
TK_BACKEND_STOP_ON_EMPTY=true
```

执行主动请求并入库：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py collect-api --import-db
```

也可以直接传接口：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py collect-api --api-url "/your/completed/video/list/api" --account shop_account_a --max-pages 10 --import-db
```

POST 接口示例：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py collect-api --method POST --api-url "/your/completed/video/list/api" --body "{""page"":""{page}"",""page_size"":""{page_size}""}" --import-db
```

主动请求会在 TK 后台页面上下文中执行 `fetch`，因此会复用当前 Chrome 的登录态，不需要把 Cookie 写到 `.env`。

如果接口使用游标分页：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py collect-api --method POST --api-url "/your/completed/video/list/api" --cursor-param cursor --next-cursor-fields next_cursor,nextCursor --has-more-fields has_more,hasMore --max-pages 20 --import-db
```

## 当前边界

- 采集主线是“监听 Network 确认接口”和“复用登录态主动请求接口”。
- 项目不会内置真实 Cookie、账号密码、历史业务数据或私有接口地址。
- 首次使用时需要用监听请求确认 TK 后台实际接口和分页字段。
- 该模块不会绕过 TK 登录、验证码或风控；它只使用你正常登录后的浏览器会话。
