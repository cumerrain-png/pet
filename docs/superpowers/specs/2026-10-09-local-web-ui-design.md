# 本机日更操作页设计

日期：2026-10-09  
状态：已批准（方案 A）

## 目标

本机浏览器完成：采集今天 → 勾选新闻 → 填语气/时长/备注 → 生成文案 → 预览素材。

## 约束

- 标准库 HTTP + `web/` 静态页；不引入 Flask/FastAPI
- 仅今天；仅本机 `127.0.0.1`
- 复用现有 `collect_candidates` / `run_produce`

## 接口

- `GET /` → 静态页
- `GET /api/today` → 日期与是否有候选/产出
- `POST /api/collect` → 采集今天
- `GET /api/candidates` → 候选 + 本地素材列表
- `POST /api/produce` → `{picked,tone,duration,extra_notes}`
- `GET /api/result` → 抖音/小红书/media 清单
- `GET /media/<path>` → 映射 `output/今天/media/`（防越权）

## 文件

- `web/index.html` `web/app.js` `web/style.css`
- `app/serve.py`
- `app/cli.py` 增加 `serve`

## 不做

选日期、改信源、配音、成片、公网部署。
