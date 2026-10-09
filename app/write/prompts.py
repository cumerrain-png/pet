from __future__ import annotations

from typing import Any


def build_messages(
    picked: list[dict[str, Any]],
    tone: str,
    duration: str,
    extra_notes: str = "",
) -> list[dict[str, str]]:
    news_blocks = []
    for i, it in enumerate(picked, start=1):
        news_blocks.append(
            "\n".join(
                [
                    f"条目{i}：",
                    f"标题：{it.get('title')}",
                    f"摘要：{it.get('summary') or '无'}",
                    f"来源：{it.get('source_name')}",
                    f"链接：{it.get('link')}",
                ]
            )
        )
    news_text = "\n\n".join(news_blocks)

    system = (
        "你是宠物短视频与小红书文案助手。"
        "只根据用户提供的新闻条目写作，不要编造未给出的数据、机构名或结论。"
        "不确定就用「据公开报道」等表述，或略过该细节。"
        "不要照抄原文长段，用口语重写。"
        "医疗相关只做一般提醒，不做诊断或处方。"
        "不写虐待细节，不煽动对立。"
    )

    user = f"""请根据下列已选新闻，生成今日内容。

【人设语气】
{tone or "轻松口语，铲屎官视角"}

【目标时长】
{duration or "45s"}

【补充要求】
{extra_notes or "无"}

【已选新闻】
{news_text}

请严格按下面格式输出（不要输出其它说明）：

===DOUYIN===
（抖音口播稿，中文口语，控制在对应时长可读完；结构：钩子→要点→落点提醒/互动→关注引导）

===XHS_TITLE===
（小红书标题，一行）

===XHS_BODY===
（小红书正文，分点，短句，结尾互动问句）

===XHS_TAGS===
（3到6个话题标签，空格分隔，带#）
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_script(raw: str) -> dict[str, str]:
    sections = {
        "douyin": "",
        "xhs_title": "",
        "xhs_body": "",
        "xhs_tags": "",
    }
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, current
        if current is None:
            buf = []
            return
        sections[current] = "\n".join(buf).strip()
        buf = []

    mapping = {
        "===DOUYIN===": "douyin",
        "===XHS_TITLE===": "xhs_title",
        "===XHS_BODY===": "xhs_body",
        "===XHS_TAGS===": "xhs_tags",
    }

    for line in raw.splitlines():
        key = line.strip()
        if key in mapping:
            flush()
            current = mapping[key]
            continue
        if current is not None:
            buf.append(line)
    flush()

    if not sections["douyin"]:
        # 容错：整段当作抖音稿
        sections["douyin"] = raw.strip()
    return sections