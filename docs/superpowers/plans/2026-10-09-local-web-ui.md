# Local Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本机 `python -m app serve` 打开页面，完成今日采集、选题、生成文案与素材预览。

**Architecture:** 标准库 `HTTPServer` 封装现有 collect/produce；`web/` 单页调用 JSON API；素材经 `/media/` 安全映射到当日目录。

**Tech Stack:** Python stdlib `http.server`，原生 HTML/CSS/JS，现有 `app.fetch` / `app.produce`。

---

### Task 1: HTTP 服务与 API

**Files:**
- Create: `app/serve.py`
- Modify: `app/cli.py`

- [ ] 实现 today/collect/candidates/produce/result/media 路由
- [ ] CLI 增加 `serve --host --port`

### Task 2: 前端单页

**Files:**
- Create: `web/index.html` `web/app.js` `web/style.css`

- [ ] 采集、勾选、语气表单、生成、结果与缩略图

### Task 3: 文档与冒烟

**Files:**
- Modify: `README.md` `DEV.md`

- [ ] 写启动说明；`GET /api/today` 冒烟通过
