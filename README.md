# Pet Daily

宠物赛道日更助手：先采集热点给你选题，再按你指定的语气调用**内网/可切换**大模型生成抖音口播稿 + 小红书笔记，并尽量下载新闻自带图片/视频。

第一版**不含配音**；口播稿可交给你本地语音模型。语音接入点预留在 `app/voice/`。

## 每日流程（推荐：本机网页）

```bash
py -3 -m app serve
# 浏览器打开 http://127.0.0.1:8765/
```

页面上可：采集今天 → 勾选新闻 → 填语气/时长/备注 → 生成文案 → 预览素材。

仍可用命令行：

1. `python -m app collect` → 生成今日候选
2. 打开 `output/YYYY-MM-DD/candidates.md`，挑选条目
3. 复制 `selection.example.json` 为根目录 `selection.json`，填写 `picked` / `tone`
4. `python -m app produce` → 文案 + 素材包
5. 人工核对后，用本地语音模型配音，再剪辑发布

## 安装

```bash
cd pet-daily
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`：

- `llm`：模型地址 / key / model 名（可随时换成别的 OpenAI 兼容接口）
- `data/sources.yaml`：信源列表（谷歌新闻 RSS + 宠物站 RSS）

当前默认以 `config.yaml` 的 `llm` 段为准（OpenAI 兼容接口）。

## selection.json 示例

```json
{
  "date": "2026-10-08",
  "picked": [1, 3, 5],
  "tone": "偏暖心科普，口语一点",
  "duration": "45s",
  "extra_notes": "不要夸大"
}
```

## 产出目录

```text
output/YYYY-MM-DD/
  candidates.md
  candidates.json
  script_douyin.txt      # 给本地语音模型
  note_xhs.md
  media/item_XX/         # 新闻图/视频；失败则有 NEED_MANUAL_MEDIA.txt
  sources.json
  README.md
```

## 后续扩展

- 本地语音：实现 `app/voice/base.py` 中的 `VoiceProvider`，并在 `config.yaml` 打开 `voice.enabled`
- A 档成片：在拿到音频后加 ffmpeg/moviepy 模板合成
- 换模型：只改 `config.yaml` 的 `llm` 段

## 注意

- **跑 `collect` 时请挂梯子**（建议全局/TUN），否则谷歌新闻、部分英文 RSS 会超时或 0 条；`produce` 调内网模型时可不挂
- 新闻原图/原视频可能有版权限制，发布前请自行判断；下不到时请自备素材
- 脚本需能同时访问新闻站点与内网模型地址
