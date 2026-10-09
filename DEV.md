# Pet Daily 开发文档（交接用）

> 项目路径：`E:\工作六\pet-daily`  
> 文档目的：换模型/换人继续开发时，按本文即可接手，无需翻聊天记录。

---

## 1. 产品目标

做**宠物赛道**日更内容助手，平台：**抖音 + 小红书**。

每日目标产出：

1. 抖音口播文案（用户自备本地语音模型配音）
2. 小红书图文草稿
3. 尽量附带新闻里的图片/视频素材包

**不做（第一版）**：配音、自动成片、自动发布。

---

## 2. 已拍板的产品决策

| 项 | 决策 |
|----|------|
| 赛道 | 宠物（国际新闻、美妆后续再说） |
| 平台 | 抖音 + 小红书 |
| 流程 | **人机协作**：先出热点清单 → 用户选题 → 用户定语气 → 再生文案/素材 |
| 选题交互 | 本机网页勾选（`python -m app serve`）或改 `selection.json` |
| 人设语气 | **不写死**，每天由用户在 `selection.json.tone` 指定 |
| 日更 | 是；通常选 2–3 条合成一条日更 |
| 成片目标 | 接受 **A 档**模板口播（字幕+素材+口播）；当前代码尚未做合成 |
| 素材 | 优先新闻自带图/视频；没有则用户自补 |
| 配音 | 第一版不做；用户有本地语音模型，后续接入 |
| 大模型 | 内网 OpenAI 兼容接口，配置可切换 |

### 内网 LLM（已测通，可切换）

```yaml
llm:
  base_url: "http://192.168.11.96:8888/v1"
  api_key: "sk-local"
  model: "deepseek-v4-flash-0731"
```

完整调用 URL：`http://192.168.11.96:8888/v1/chat/completions`  
`supportsImages: false` → 只传文字，不要把图片塞进该模型。

换模型：只改 `config.yaml` 的 `llm` 段（任意 OpenAI 兼容接口）。

---

## 3. 目标每日工作流

```text
python -m app serve
  → 浏览器 http://127.0.0.1:8765/
  → 采集 / 勾选 / 填语气 / 生成 / 看素材

或命令行：
python -m app collect
  → output/YYYY-MM-DD/candidates.md|.json

用户阅读清单，编辑 selection.json（picked + tone）

python -m app produce
  → script_douyin.txt
  → note_xhs.md
  → media/item_XX/
  → sources.json

用户核对文案 → 本地语音模型配音 → 剪辑发布
```

`selection.json` 字段：

```json
{
  "date": "2026-10-08",
  "picked": [1, 3, 5],
  "tone": "偏暖心科普，口语一点，结尾问互动问题",
  "duration": "45s",
  "extra_notes": "不要夸大，不确定细节别写死"
}
```

---

## 4. 仓库结构

```text
pet-daily/
├── DEV.md                 # 本文：开发交接文档
├── README.md              # 使用说明（偏用户）
├── config.yaml            # 主配置（LLM / 采集 / 路径 / 语音开关）
├── requirements.txt
├── selection.example.json
├── selection.json         # 用户选题文件（已 gitignore）
├── web/                   # 本机操作页（serve 静态资源）
├── data/
│   └── sources.yaml       # 信源列表
├── app/
│   ├── __main__.py        # python -m app
│   ├── cli.py             # collect / produce / serve
│   ├── serve.py           # 本机 HTTP：采集/选题/生成/素材
│   ├── config.py          # 读配置、输出目录
│   ├── produce.py         # 选题→文案→下素材
│   ├── fetch/
│   │   └── collect.py     # RSS/谷歌新闻采集、去重、关键词过滤、抽媒体链接
│   ├── report/
│   │   └── candidates.py  # 写 candidates.md / .json
│   ├── write/
│   │   ├── llm.py         # OpenAI 兼容客户端
│   │   └── prompts.py     # 文案 prompt + 分段解析
│   ├── media/
│   │   ├── extract.py     # RSS 无图时用 trafilatura/HTML 回源抽图
│   │   └── download.py    # 下载新闻图/视频；失败写 NEED_MANUAL_MEDIA.txt
│   └── voice/
│       └── base.py        # VoiceProvider 抽象（未实现具体 TTS）
└── output/YYYY-MM-DD/     # 日产出（已 gitignore）
```

---

## 5. 已实现功能

### 5.1 `collect`

- 读 `data/sources.yaml`
- 支持 `type: rss` 与 `type: google_news`（拼 Google News RSS URL）
- 时间窗、每源上限、总候选上限可配
- 关键词 include/exclude
- 标题去重（fingerprint）
- 从 entry 抽图片/视频 URL（enclosure / media / HTML img）
- 输出 `candidates.md` + `candidates.json`

### 5.2 `produce`

- 读 `selection.json` + 当日 `candidates.json`
- 调内网 LLM 生成：
  - 抖音口播 → `script_douyin.txt`
  - 小红书标题/正文/标签 → `note_xhs.md`
- 下载所选条目媒体到 `media/item_XX/`（RSS 无图则打开原文，trafilatura + og:image 抽图）
- 写下 `sources.json`（溯源）与产出目录 `README.md`
- 模型原始输出备份为 `script_raw_model.txt`

### 5.3 语音预留

- `app/voice/base.py`：`VoiceProvider` / `get_voice_provider`
- `config.yaml`：`voice.enabled: false`
- **尚未**对接用户本地语音模型

### 5.4 文案格式约定（模型输出）

`app/write/prompts.py` 要求模型按区块输出：

```text
===DOUYIN===
...
===XHS_TITLE===
...
===XHS_BODY===
...
===XHS_TAGS===
...
```

解析失败时整段回退为抖音稿。

---

## 6. 当前阻塞 / 已知问题（重要）

### 6.1 外网采集依赖梯子 + 冲突/温馨双轨

跑 `collect` 时挂梯子（建议全局/TUN）。清单目标是 **当天 100 条**，用户再勾选几条：

- 只保留 `Asia/Shanghai` 自然日当天；不够 100 也不用旧闻凑
- `data/sources.yaml`：`track: conflict | warm | hot`；谷歌检索 `when:1d`；热点源覆盖中/港/台/美/英/澳/加/印/日/韩/新
- `config.yaml`：`max_candidates: 100`，`same_day_only: true`，`balance_tracks: false`（广覆盖优先，冲突/温馨仍带标签）
- 标题去媒体后缀去重；每个信源先最多 `diverse_per_source` 条

无梯子时仍可能 0 条。`produce` 只打内网 LLM，可不挂代理。

### 6.2 未实现模块

- [ ] A 档视频合成（ffmpeg/moviepy：字幕 + 素材，音频后期拼）
- [ ] 本地语音模型对接（`VoiceProvider` 实现）
- [ ] 自动发布抖音/小红书
- [x] 本机网页选题（`python -m app serve`，仅今天）

### 6.3 其它注意

- 新闻原图/原视频有**版权风险**，程序只负责尽量下载，发布合规由用户判断
- 跑 `collect` 时挂梯子；跑脚本的机器还需能访问内网 LLM（`produce`）
- 控制台中文在部分终端会乱码，不影响文件 UTF-8 写入

---

## 7. 运行方式

```bash
cd E:\工作六\pet-daily
pip install -r requirements.txt

# 采集
python -m app collect
# 可选：python -m app collect --date 2026-10-08

# 填写 selection.json 后
python -m app produce
```

依赖见 `requirements.txt`：`feedparser`、`httpx`、`openai`、`PyYAML`、`beautifulsoup4`、`lxml`、`tenacity`、`rich`。

Python 环境曾用：**3.14.6**。

---

## 8. 建议接手开发顺序

1. **采集**（方案 A 已落地：挂梯子 + 开谷歌新闻 + 浏览器 UA；挂梯子后可出满额候选）
2. **回归 produce**
   - 用真实 `selection.json` 调内通网 LLM，检查文案格式解析
   - 验证媒体下载与 `NEED_MANUAL_MEDIA.txt` 逻辑（谷歌新闻条目常无直链图）
3. **语音适配**
   - 按用户本地语音 API 实现 `VoiceProvider`
   - `script_douyin.txt` → 音频文件
4. **A 档成片**
   - 竖屏 1080×1920；素材 + 字幕（+ 用户生成的音频）
5. **体验优化**
   - 可选显式代理、国内源/inbox 保底、信源健康检查

---

## 9. 关键配置速查

### `config.yaml`

- `llm.*`：模型
- `collect.*`：时间窗、条数、关键词
- `paths.output_dir` / `selection_file`
- `voice.*`：预留，默认关闭
- `network.user_agent` / `timeout_seconds`

### `data/sources.yaml`

```yaml
sources:
  - id: xxx
    name: 显示名
    type: rss | google_news
    url: "..."          # rss 必填
    query/hl/gl/ceid:   # google_news 用
    enabled: true|false
    lang: zh|en
```

---

## 10. 文案与风控约定（写进 prompt 的）

- 只基于用户选中的新闻写，不编造
- 口语重写，不长段照抄
- 医疗只做一般提醒，不做诊断处方
- 不写虐待细节、不煽动对立
- 抖音结构：钩子 → 要点 → 落点/互动 → 关注引导
- 小红书：偏搜索标题 + 分点短句 + 标签

语气**不写死在代码里**，以当天 `tone` 为准。

---

## 11. 与用户的协作边界

- 选题、语气：用户每天决定
- 事实核对、发布、版权素材替换：用户
- 程序：采集整理、按选择生成文案、尽量下媒体、后续接语音/成片

---

## 12. 给下一个模型的一句话状态

> 脚手架和 `collect`/`produce` 主链路已搭好；外网采集采用「跑 collect 时挂梯子」策略，谷歌新闻已启用、UA 已偏浏览器。挂梯子后可稳定出候选。下一步可接：真实选题跑通 `produce` → 语音 → A 档成片；无梯子保底再考虑国内源/inbox。
