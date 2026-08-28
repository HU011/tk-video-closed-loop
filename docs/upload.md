# 上传说明

上传项目时保留源码和配置样例，排除本地运行文件。

## 应上传

- `app.py`
- `core/`
- `collection/`
- `downloading/`
- `screening/`
- `pipeline/`
- `services/`
- `integrations/`
- `media/`
- `static/`
- `scripts/`
- `tests/`
- `docs/`
- `examples/`
- `README.md`
- `requirements.txt`
- `.env.example`
- `config.example.json`
- `agent.md`
- `start.bat`
- `start.ps1`

## 不应上传

- `venv/`
- `.env`
- `config.json`
- `data/app.db`
- `uploads/` 中的真实素材
- `outputs/` 中的生成结果
- `runtime/` 中的 Chrome 登录会话和运行缓存
- `__pycache__/`
- `*.pyc`

## 打包

```powershell
cd D:\开发\github
.\scripts\package_upload.ps1
```

输出：

```text
tk_closed_loop_upload.zip
```
