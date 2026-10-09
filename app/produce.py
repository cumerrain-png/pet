from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from app.config import output_dir, selection_path
from app.media.download import download_media_for_items
from app.write.llm import chat
from app.write.prompts import build_messages, parse_script

console = Console()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_selection(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}。请复制 selection.example.json 为 selection.json 并填写 picked/tone。"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("picked"):
        raise ValueError("selection.json 中 picked 不能为空")
    return data


def load_candidates(day_dir: Path) -> dict[str, Any]:
    path = day_dir / "candidates.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到 {path}，请先运行 collect。")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_picked(candidates: dict[str, Any], picked_ids: list[int]) -> list[dict[str, Any]]:
    by_id = {int(it["id"]): it for it in candidates.get("items") or []}
    resolved: list[dict[str, Any]] = []
    missing: list[int] = []
    for pid in picked_ids:
        pid = int(pid)
        if pid not in by_id:
            missing.append(pid)
        else:
            resolved.append(by_id[pid])
    if missing:
        raise ValueError(f"selection 中的 id 不存在于候选清单: {missing}")
    return resolved


def write_outputs(
    day_dir: Path,
    selection: dict[str, Any],
    picked: list[dict[str, Any]],
    script: dict[str, str],
    media_manifest: list[dict[str, Any]],
    raw_model: str,
) -> None:
    (day_dir / "script_douyin.txt").write_text(script["douyin"] + "\n", encoding="utf-8")

    xhs = "\n".join(
        [
            script.get("xhs_title") or "",
            "",
            script.get("xhs_body") or "",
            "",
            script.get("xhs_tags") or "",
            "",
        ]
    )
    (day_dir / "note_xhs.md").write_text(xhs, encoding="utf-8")
    (day_dir / "script_raw_model.txt").write_text(raw_model + "\n", encoding="utf-8")

    sources_payload = {
        "date": selection.get("date") or day_dir.name,
        "tone": selection.get("tone"),
        "duration": selection.get("duration"),
        "picked": [
            {
                "id": it["id"],
                "title": it.get("title"),
                "link": it.get("link"),
                "source_name": it.get("source_name"),
            }
            for it in picked
        ],
        "media": media_manifest,
        "voice": {
            "enabled": False,
            "note": "第一版不配音。将 script_douyin.txt 交给本地语音模型即可；后续可接 app/voice。",
        },
    }
    (day_dir / "sources.json").write_text(
        json.dumps(sources_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    readme = f"""# 产出说明 {day_dir.name}

## 文件
- `script_douyin.txt`：抖音口播稿（可直接送本地语音模型）
- `note_xhs.md`：小红书标题/正文/标签
- `media/`：按条目下载的新闻图片/视频；若有 `NEED_MANUAL_MEDIA.txt` 请自行补素材
- `sources.json`：选用新闻与素材清单，便于核对
- `script_raw_model.txt`：模型原始输出（排查用）

## 下一步
1. 核对事实与语气，按需改 `script_douyin.txt` / `note_xhs.md`
2. 用本地语音模型对 `script_douyin.txt` 生成音频
3. 用 `media/` 素材 + 音频做 A 档模板成片后发布
"""
    (day_dir / "README.md").write_text(readme, encoding="utf-8")


def run_produce(cfg: dict[str, Any], day: str | None = None) -> Path:
    sel_path = selection_path(cfg)
    selection = load_selection(sel_path)
    day = day or selection.get("date") or _today()
    day_dir = output_dir(cfg, day)

    candidates = load_candidates(day_dir)
    picked = resolve_picked(candidates, list(selection["picked"]))
    console.print(f"[cyan]已选 {len(picked)} 条[/cyan]，语气：{selection.get('tone') or '（未填，用默认）'}")

    messages = build_messages(
        picked=picked,
        tone=str(selection.get("tone") or ""),
        duration=str(selection.get("duration") or "45s"),
        extra_notes=str(selection.get("extra_notes") or ""),
    )
    console.print("[cyan]调用本地模型生成文案...[/cyan]")
    raw = chat(cfg, messages)
    script = parse_script(raw)

    net = cfg.get("network") or {}
    console.print("[cyan]下载新闻媒体素材...[/cyan]")
    media_manifest = download_media_for_items(
        items=picked,
        media_dir=day_dir / "media",
        user_agent=str(net.get("user_agent") or "PetDailyBot/0.1"),
        timeout=float(net.get("timeout_seconds") or 30),
    )

    write_outputs(day_dir, selection, picked, script, media_manifest, raw)
    console.print(f"[green]完成[/green] → {day_dir}")
    return day_dir