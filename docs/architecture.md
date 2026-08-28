# 架构

## 模块

- `app.py`：标准库 HTTP 服务、JSON API、静态页面、受限文件下载。
- `collection/`：采集模块，支持 TikTok oEmbed、CSV、JSON、手动行导入。
- `downloading/`：下载模块，支持直链视频和可选 `yt-dlp` 下载。
- `screening/`：筛选模块，封装爆款视频和样品风险达人输出。
- `pipeline/`：采集后筛选的闭环编排。
- `core/db.py`：SQLite 初始化、通用写入、账号/达人/产品 upsert。
- `services/importer.py`：CSV/JSON 视频数据导入。
- `services/analyzer.py`：爆款评分、白嫖样品达人评分。
- `services/replicator.py`：复刻任务编排和后台执行。
- `media/ffmpeg_tools.py`：探测时长、切分并转为 720x1280 参考片段、抽尾帧、拼接、mock 视频。
- `integrations/apimart_client.py`：APIMart JSON 请求、图片上传、结果下载。
- `integrations/gemini_client.py`：APIMart Gemini 原生多模态 `generateContent` 生成分段提示词；可兼容旧 Chat Completions。
- `integrations/seedance_client.py`：APIMart Seedance 任务提交、轮询、视频和尾帧下载；默认 mock。
- `static/`：原生前端工作台。

## 数据流

```text
采集/下载/导入 -> SQLite -> 分析评分 -> 可视化筛选 -> 复刻任务
复刻任务 -> FFmpeg 切片 -> APIMart Gemini 分析当前片段/产品图/尾帧 -> APIMart Seedance 分段生成 -> Seedance 返回尾帧 -> 拼接
```

## 文件边界

所有数据库、上传文件、切分片段、生成结果都写入当前项目目录：

- `data/app.db`
- `uploads/`
- `outputs/`

服务端会拒绝复刻当前项目目录外的本地文件。
