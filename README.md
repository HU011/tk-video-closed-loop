# TikTok 达人带货视频采集、爆款筛选与复刻生成

这是一个面向 TikTok 达人带货视频的本地化工作台，用于把视频数据采集、爆款筛选、样品风险判断和复刻生成串成一套可配置流程。

项目默认使用本地 SQLite 存储数据，不内置账号 Cookie、历史业务数据或真实密钥。下载后按文档配置 `ffmpeg/ffprobe`、APIMart Key 和可选 `yt-dlp`，即可在本地完成基础使用。

## 核心流程

1. 采集 TikTok 视频链接、CSV 或 JSON 数据。
2. 下载或上传原始视频素材。
3. 入库账号、达人、产品和视频指标。
4. 自动计算爆款视频评分。
5. 自动筛选样品风险达人。
6. 在页面选择视频并上传产品图。
7. 调用 Gemini 生成分段复刻提示词。
8. 调用 Seedance 2.0 分段生成视频并返回尾帧。
9. 使用尾帧衔接下一段，最后拼接成片。

## 功能模块

- `collection/`：采集模块，支持 TikTok oEmbed、URL 列表、CSV、JSON 和手动数据行。
- `downloading/`：下载模块，支持 MP4 直链下载；配置 `yt-dlp` 后可下载 TikTok 页面链接。
- `screening/`：筛选模块，计算爆款视频和样品风险达人。
- `pipeline/`：流程编排模块，提供采集后立即筛选的入口。
- `services/replicator.py`：复刻模块，负责 60 秒限制、15 秒切片、提示词生成、Seedance 调用、尾帧衔接和视频拼接。
- `static/`：本地 Web 页面，提供采集、视频库、样品达人、复刻任务和导入界面。

## 项目结构

```text
tk-video-closed-loop/
├─ app.py                         # HTTP 服务、API 路由、静态页面入口
├─ README.md                      # 中文使用说明
├─ requirements.txt               # Python 依赖说明
├─ .env.example                   # 环境变量配置样例
├─ config.example.json            # JSON 配置样例
├─ start.bat                      # Windows 启动脚本
├─ start.ps1                      # PowerShell 启动脚本
├─ agent.md                       # 本地开发边界规则
├─ core/                          # 配置、路径边界、SQLite 数据库
│  ├─ db.py                       # 表结构、连接、通用 upsert
│  ├─ paths.py                    # 项目目录约束和路径工具
│  └─ settings.py                 # .env/config.json 配置加载
├─ collection/                    # 采集模块
│  ├─ collector.py                # URL/CSV/JSON 采集入口
│  └─ tiktok_oembed.py            # TikTok oEmbed 元数据采集
├─ downloading/                   # 视频下载模块
│  └─ video_downloader.py         # 直链下载和可选 yt-dlp 下载
├─ screening/                     # 筛选模块
│  └─ screener.py                 # 爆款视频和样品风险输出
├─ pipeline/                      # 闭环编排
│  └─ closed_loop.py              # 采集后立即筛选
├─ services/                      # 业务服务
│  ├─ analyzer.py                 # 热度评分和样品风险评分
│  ├─ importer.py                 # CSV/JSON 行导入
│  └─ replicator.py               # 分段复刻任务编排
├─ integrations/                  # 第三方模型/API 适配
│  ├─ apimart_client.py           # APIMart 请求、上传、下载
│  ├─ gemini_client.py            # Gemini 提示词生成
│  └─ seedance_client.py          # Seedance 2.0 视频生成和尾帧
├─ media/                         # 媒体处理
│  └─ ffmpeg_tools.py             # 切片、探测、抽帧、拼接
├─ static/                        # Web 前端
│  ├─ index.html                  # 页面结构
│  ├─ app.js                      # 前端交互和 API 调用
│  └─ styles.css                  # 页面样式
├─ scripts/                       # 辅助脚本
│  ├─ check_setup.py              # 环境检查
│  ├─ run_checks.ps1              # 编译、测试、基础检查
│  ├─ package_upload.ps1          # 上传打包
│  └─ seed_demo.py                # 示例数据脚本
├─ tests/                         # 单元测试
├─ examples/                      # 示例 CSV 数据
├─ data/                          # 本地数据库目录，默认不提交真实数据
├─ uploads/                       # 上传素材目录，默认不提交真实素材
└─ outputs/                       # 生成结果目录，默认不提交生成视频
```

## 快速开始

### 1. 克隆项目

```powershell
git clone https://github.com/HU011/tk-video-closed-loop.git
cd tk-video-closed-loop
```

### 2. 创建 Python 环境

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Python 侧运行时只使用标准库，`requirements.txt` 用于说明外部工具依赖。

### 3. 创建本地配置

```powershell
Copy-Item .env.example .env
```

基础采集和筛选不需要真实 API Key。真实复刻生成需要配置 APIMart 和公网素材访问地址。

### 4. 检查环境

```powershell
.\venv\Scripts\python.exe scripts\check_setup.py --mode basic
```

真实复刻前运行：

```powershell
.\venv\Scripts\python.exe scripts\check_setup.py --mode real
```

### 5. 启动服务

```powershell
.\venv\Scripts\python.exe app.py
```

浏览器打开：

```text
http://127.0.0.1:8765
```

也可以使用：

```powershell
.\start.ps1
```

## 配置说明

复制 `.env.example` 为 `.env` 后按需修改。

### 基础配置

```env
APP_HOST=127.0.0.1
APP_PORT=8765
DATABASE_PATH=data/app.db
```

### 真实复刻生成

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
```

`PUBLIC_BASE_URL` 必须能被 APIMart/Seedance 访问，并能反向访问当前服务的 `/files/...` 素材地址。真实生成时，本地切片视频、产品图和尾帧图都需要通过这个地址被模型服务拉取。

### 视频下载

```env
YTDLP_BIN=yt-dlp
```

- MP4 等直链视频可直接下载。
- TikTok 页面链接下载依赖本机安装 `yt-dlp`。
- 不配置 `yt-dlp` 时，系统仍可采集链接和导入数据，但不会下载页面视频。

## 页面使用

1. 打开 `http://127.0.0.1:8765`。
2. 进入“采集”，粘贴 TikTok 链接，或粘贴 `examples/sample_videos.csv` 示例数据。
3. 点击“采集并筛选”或“导入并筛选”。
4. 在“视频库”查看视频和热度评分。
5. 选择一个视频，上传产品图。
6. 点击“开始复刻”。
7. 在“复刻任务”查看分段提示词、生成片段、尾帧和最终成片。

## CSV 字段

最小字段：

```csv
account_name,username,title,video_url,views,likes,comments,shares,orders,gmv,duration_seconds,product_name,sample_received_count,posted_video_count
```

可选字段：

```csv
original_video_path,product_image_path,account_handle,nickname,region,category,follower_count,commission_rate,cover_path
```

需要复刻的视频必须有 `original_video_path`，并且文件必须位于项目目录内，例如：

```text
uploads/video/demo.mp4
```

## 复刻生成逻辑

1. 原视频最多处理 60 秒。
2. 使用 FFmpeg 切成最多 4 段，每段不超过 15 秒。
3. 第 1 段使用当前片段、产品图和完整原视频信息生成提示词。
4. 第 2-4 段使用当前片段、产品图和上一段 Seedance 返回尾帧继续生成。
5. Seedance 请求固定带 `return_last_frame=true`。
6. 优先使用接口返回的尾帧 URL；如果接口未返回尾帧，才本地抽帧兜底。
7. 所有片段生成完成后拼接为最终视频。

输出目录：

```text
outputs/replication_job_xxxxx/final_replicated_video.mp4
```

## API

- `GET /api/health`：健康检查。
- `GET /api/modules`：查看采集、下载、筛选、复刻模块状态。
- `POST /api/collect`：采集 URL、CSV 或 JSON 数据。
- `POST /api/closed-loop/collect-screen`：采集后立即筛选。
- `POST /api/screen`：重新计算筛选结果。
- `POST /api/download-video`：下载视频并绑定到视频记录。
- `POST /api/replicate`：创建复刻任务。
- `GET /api/jobs`：查看复刻任务列表。

## 本地检查

运行全部基础检查：

```powershell
.\scripts\run_checks.ps1
```

当前检查包含：

- Python 编译检查。
- 单元测试。
- 项目目录写入检查。
- FFmpeg、FFprobe、yt-dlp、APIMart 配置状态提示。

## 上传和安全

项目已配置 `.gitignore`，默认排除：

- `.env`
- `config.json`
- `venv/`
- `data/` 中的本地数据库
- `uploads/` 中的真实素材
- `outputs/` 中的生成结果
- `__pycache__/`
- `*.pyc`
- `*.zip`

打包上传可运行：

```powershell
.\scripts\package_upload.ps1
```

## 注意事项

- 不要把真实 API Key、Cookie、账号密码或业务数据提交到仓库。
- 本项目不内置 TikTok 登录态采集器；当前采集入口面向 URL、CSV、JSON 和可选 `yt-dlp` 下载。
- 真实复刻生成依赖 APIMart、FFmpeg 和公网素材访问地址。
- Seedance 2.0 单次生成最长 15 秒，因此长视频会按 15 秒分段生成后拼接。
