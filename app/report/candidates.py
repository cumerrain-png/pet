from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def render_markdown(day: str, items: list[dict[str, Any]]) -> str:
    lines = [
        f"# {day} 宠物热点候选",
        "",
        f"共 {len(items)} 条。请复制 `selection.example.json` 为项目根目录的 `selection.json`，填写 `picked` 与 `tone` 后执行 `produce`。",
        "",
    ]
    if not items:
        lines.append("_今日暂无候选，可放宽关键词或增加信源。_")
        return "\n".join(lines) + "\n"

    labels = {"hot": "热点", "conflict": "冲突", "warm": "温馨"}
    counts = {key: sum(1 for it in items if it.get("track") == key) for key in labels}
    other = len(items) - sum(counts.values())
    parts = [f"{label} {counts[key]}" for key, label in labels.items() if counts[key]]
    if other:
        parts.append(f"其它 {other}")
    breakdown = " / ".join(parts) if parts else "无分类"
    lines.append(f"_当天候选（{breakdown}）。勾选其中几条再生成。_")
    lines.append("")

    track_label = labels

    for it in items:
        img_mark = "✓" if it.get("has_image") else "✗"
        vid_mark = "✓" if it.get("has_video") else "✗"
        tag = track_label.get(it.get("track") or "", it.get("track") or "其它")
        lines.extend(
            [
                f"## [{it['id']}] 【{tag}】{it['title']}",
                "",
                f"- 摘要：{it.get('summary') or '（无摘要）'}",
                f"- 来源：{it.get('source_name')} | 时间：{_fmt_time(it.get('published_at'))}",
                f"- 媒体：封面/图片 {img_mark} / 视频 {vid_mark}",
                f"- 链接：{it.get('link')}",
                "",
            ]
        )
    return "\n".join(lines)


def write_candidates(day_dir: Path, day: str, items: list[dict[str, Any]]) -> tuple[Path, Path]:
    md_path = day_dir / "candidates.md"
    json_path = day_dir / "candidates.json"
    md_path.write_text(render_markdown(day, items), encoding="utf-8")
    payload = {
        "date": day,
        "count": len(items),
        "items": items,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path