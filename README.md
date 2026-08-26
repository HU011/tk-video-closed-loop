# TK 带货视频闭环

这是一个放在 `D:\开发\github` 内独立运行的闭环项目，不修改外部三个参考项目。

## 能否下载后直接使用

可以。下载项目后按下面步骤配置，即可完成基础闭环：

```text
采集 TikTok 链接/CSV -> 入库 -> 筛选爆款和样品风险达人 -> 页面选择视频 -> 上传产品图 -> 分段复刻 -> 拼接成片
```

基础数据采集和筛选只需要 Python。视频复刻需要配置 `ffmpeg/ffprobe`。TikTok 页面链接下载需要可选配置 `yt-dlp`。真实 Gemini/Seedance 生成需要 `APIMART_API_KEY` 和公网 `PUBLIC_BASE_URL`。

## 当前已实现

- 采集模块：支持 TikTok 链接 oEmbed 元数据采集、CSV/JSON/手动行导入、多账号归属字段。
- 下载模块：支持直链视频下载；如本机配置 `yt-dlp`，可下载 TikTok 页面链接视频。
- 多账号、达人、产品、带货视频本地入库。
- CSV 或单条录入视频指标，也可在“采集”页面直接采集并筛选。
- 爆款视频评分：播放、互动、订单、GMV、视频时长综合计算。
- 白嫖样品达人筛选：样品领取、回传视频、成交、GMV 综合计算。
- Web 可视化页面：总览、采集、视频库、样品达人、复刻任务、导入。
- 复刻任务编排：最长 60 秒，FFmpeg 切成最多 4 段，每段不超过 15 秒。
- Gemini 分段提示词：通过 APIMart Chat Completions 分析完整视频、当前片段、产品图、上一段尾帧。
- Seedance 2.0 分段生成：默认 `mock` 模式跑通流程；真实模式通过 APIMart 配置切换。
- 每段生成时设置 `return_last_frame=true`，优先使用 Seedance 返回的尾帧 URL，作为下一段首帧；最后拼接成完整复刻视频。

## 启动

1. 创建环境：

```powershell
cd D:\开发\github
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. 复制配置：

```powershell
Copy-Item .env.example .env
```

3. 检查本机环境：

```powershell
.\venv\Scripts\python.exe scripts\check_setup.py --mode basic
```

4. 启动：

```powershell
cd D:\开发\github
.\venv\Scripts\python.exe app.py
```

然后打开：

```text
http://127.0.0.1:8765
```

也可以运行：

```powershell
.\start.ps1
```

或一次性运行基础检查：

```powershell
.\scripts\run_checks.ps1
```

## 配置

复制 `.env.example` 为 `.env`，或复制 `config.example.json` 为 `config.json`。

默认 `SEEDANCE_PROVIDER=mock`，不会调用真实模型，但会用 FFmpeg 生成可拼接的本地测试视频。

真实模型需要：

- `APIMART_API_KEY`
- `SEEDANCE_PROVIDER=apimart`
- `PUBLIC_BASE_URL`

`PUBLIC_BASE_URL` 必须是 APIMart/Seedance 服务可访问到的公网地址，并能反向访问当前服务的 `/files/...` 文件，否则真实视频、产品图、首帧图无法被模型拉取。

如果要下载 TikTok 页面链接视频，还需要安装或配置 `yt-dlp`：

```env
YTDLP_BIN=yt-dlp
```

如果只是下载 `.mp4` 直链，不需要 `yt-dlp`。

真实复刻配置示例：

```env
APIMART_API_KEY=你的_APIMart_Key
GEMINI_PROVIDER=apimart
GEMINI_MODEL=gemini-2.5-flash

SEEDANCE_PROVIDER=apimart
SEEDANCE_MODEL=seedance-2.0
SEEDANCE_ENDPOINT=https://api.apimart.ai/v1/videos/generations

PUBLIC_BASE_URL=https://你的公网域名
FFMPEG_BIN=ffmpeg
FFPROBE_BIN=ffprobe
YTDLP_BIN=yt-dlp
```

真实复刻前运行：

```powershell
.\venv\Scripts\python.exe scripts\check_setup.py --mode real
```

## 使用流程

1. 打开页面 `http://127.0.0.1:8765`。
2. 进入“采集”，粘贴 TikTok 链接，或把 `examples/sample_videos.csv` 内容粘贴进 CSV 区。
3. 点击“采集并筛选”或“导入并筛选”。
4. 进入“视频库”，选择爆款视频。
5. 上传产品图，选择最长生成时长。
6. 点击“开始复刻”。
7. 进入“复刻任务”查看分段、尾帧和最终成片。

## CSV 字段

最小字段：

```csv
account_name,username,title,video_url,views,likes,comments,shares,orders,gmv,duration_seconds,product_name,sample_received_count,posted_video_count
```

可选字段：

```csv
original_video_path,product_image_path,account_handle,nickname,region,category,follower_count,commission_rate,cover_path
```

需要复刻的视频必须有 `original_video_path`，并且文件必须位于当前项目目录内，例如 `uploads/video/demo.mp4`。

## 复刻流程

1. 用户选择视频和产品图。
2. 系统校验原视频和产品图都在当前项目目录内。
3. 原视频最多取 60 秒。
4. FFmpeg 切分为最多 4 个 15 秒片段。
5. 第 1 段：当前片段 + 产品图 + 完整原视频 URL 给 Gemini 生成提示词，再给 Seedance 生成。
6. 第 2-4 段：当前片段 + 产品图 + 上一段 Seedance 返回尾帧图给 Gemini 和 Seedance。
7. Seedance 请求固定带 `return_last_frame=true`，任务完成后下载返回的尾帧 URL；如果接口没给尾帧，才本地抽帧兜底。
8. 所有片段拼接为 `outputs/replication_job_xxxxx/final_replicated_video.mp4`。

## 模块目录

- `collection/`：采集模块，负责 URL、CSV、JSON、oEmbed 元数据采集。
- `downloading/`：下载模块，负责直链下载和可选 `yt-dlp` 下载。
- `screening/`：筛选模块，统一输出爆款视频和样品风险达人。
- `pipeline/`：闭环编排，当前提供采集后立即筛选。
- `services/replicator.py`：复刻模块，负责分段、提示词、Seedance 生成、尾帧衔接、拼接。

## 注意

- 项目不会修改 `D:\开发\视频抓取`、`D:\开发\TK达人数据可视化`、`D:\开发\TK数据采集`。
- 不要把真实密钥写进仓库；放到 `.env` 或本地 `config.json`。
- 真实 Seedance API 的素材地址通常不能是 `localhost`，需要公网可访问 URL。
- 上传前可运行 `.\scripts\package_upload.ps1`，它会排除 `venv/`、本地数据库、上传素材、生成结果和密钥文件。
- 仓库没有内置旧项目的历史数据、账号 Cookie、密钥或浏览器登录采集器；当前采集入口面向 URL/CSV/JSON 和可选 `yt-dlp` 下载。
