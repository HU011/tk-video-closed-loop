# TK 后台自动化采集模块

`tk_automation/` 是独立模块，不集成到 Web 页面。它用于辅助登录 TK 后台、读取邮箱验证码、监听真实 Network 请求、复用已登录页面主动请求后台 API，并把已完成视频链接导入当前项目数据库。

TK 后台采集只有两条主线：

1. 监听请求：你在已登录 TK 后台打开“已完成/已发布视频”相关页面并翻页，程序监听 Network，记录真实接口的 `url`、`method`、`headers`、`body`、分页参数和返回结构，并从 response 中提取视频链接。
2. 自动发现并采集：监听到候选列表接口后，程序会根据响应字段和分页特征生成 `suggestions`，选择最高分接口继续翻页采集。
3. 主动请求：确认接口后，程序复用已登录 Chrome 页面里的 Cookie/session，在页面上下文中执行 `fetch`，分页请求已完成视频列表并入库。

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
│  ├─ discovery.py               # 从 Network 响应中识别候选列表接口和分页字段
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

`headers`、`query` 和 `post_data` 会默认脱敏 `cookie`、`authorization`、`csrf/token/session` 等敏感字段。监听模式的用途是确认真实接口、请求方法、分页字段、请求体和返回结构。

监听输出还会包含 `suggestions`：

```json
{
  "score": 78,
  "reasons": ["HTTP 200", "响应是 JSON", "已提取 12 条视频记录"],
  "env": {
    "TK_BACKEND_API_URL": "https://.../completed/video/list?csrf_token=%2A%2A%2A",
    "TK_BACKEND_API_METHOD": "POST",
    "TK_BACKEND_API_BODY": "{\"page\":\"{page}\",\"page_size\":\"{page_size}\"}",
    "TK_BACKEND_PAGE_PARAM": "page",
    "TK_BACKEND_PAGE_SIZE_PARAM": "page_size"
  }
}
```

`env` 是给本地 `.env` 参考用的脱敏版本；真实自动采集不会把敏感值写入文件，只在当前进程中复用已登录 Chrome 的上下文。

### 怎么确认目标接口

监听时不要随便拿第一个请求当采集接口，按下面标准判断：

1. 在 TK 后台页面里触发列表加载，例如进入已完成视频列表、切换筛选条件、点击下一页。
2. 找到重复出现的列表接口，通常是 `GET` 或 `POST`，状态码为 `200`，响应类型为 JSON。
3. 确认 response 里有视频相关字段，例如 TikTok 视频链接、视频 ID、达人账号、商品、播放、点赞、评论、订单、GMV、发布时间、发布状态。
4. 翻页时确认同一个接口的 `page/page_size`、`offset/limit` 或 `cursor/next_cursor` 参数会变化。
5. 继续翻到最后，确认结束条件是空列表、`has_more=false`、`has_next=false`、没有 `next_cursor`，或下一页游标不再变化。
6. 把确认后的 `url`、`method`、必要 `headers`、`query`、`post_data`、分页参数、返回字段记录到本地 `.env` 或命令行参数。

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

自动发现接口并继续翻页采集：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py collect-auto --request-url-contains video --listen-timeout 120 --max-pages 10 --import-db
```

`collect-auto` 的流程是：连接已登录 Chrome -> 监听当前 TK 页面 Network -> 解析返回 JSON 里的视频记录 -> 根据字段和分页参数生成候选接口 -> 用最高分接口在页面上下文执行 `fetch` -> 翻页采集 -> 可选入库。

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

### 哪些会自动补全

主动请求运行在已登录 TK 后台页面里，所以浏览器会自动补全这些环境信息：

- `Cookie/session`：由 `credentials: "include"` 自动携带。
- `User-Agent`、`sec-ch-ua` 等浏览器指纹请求头：由 Chrome 自己发送。
- `Origin`、`Referer`：同源或跨源请求时由浏览器按规则生成。
- 禁止脚本手动设置的请求头，例如 `cookie`、`user-agent`：不需要也不能写进配置。

这些不会自动知道，需要你通过监听请求确认后配置：

- 接口路径或完整 URL。
- 请求方法：GET 或 POST。
- 业务筛选参数：达人、商品、任务状态、发布时间、视频状态等。
- 分页参数：`page/page_size`、`offset/limit`、`cursor/next_cursor`、`has_more`。
- 必要的自定义请求头，例如 `x-csrf-token`、业务网关 token、特殊 `content-type`。这类值如果会过期，只能放本地 `.env`，不要提交到仓库。

TK 账号密码不需要输入到项目里。你只需要在独立 Chrome 中正常登录；邮箱配置只用于可选读取验证码，不是保存 TK 账号密码。

如果接口使用游标分页：

```powershell
.\venv\Scripts\python.exe scripts\tk_collect_completed_videos.py collect-api --method POST --api-url "/your/completed/video/list/api" --cursor-param cursor --next-cursor-fields next_cursor,nextCursor --has-more-fields has_more,hasMore --max-pages 20 --import-db
```

## 当前边界

- 采集主线是“监听 Network 确认接口”和“复用登录态主动请求接口”。
- 项目不会内置真实 Cookie、账号密码、历史业务数据或私有接口地址。
- 首次使用时需要用监听请求确认 TK 后台实际接口和分页字段。
- 该模块不会绕过 TK 登录、验证码或风控；它只使用你正常登录后的浏览器会话。
