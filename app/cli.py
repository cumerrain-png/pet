from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from rich.console import Console

from app.config import load_config, output_dir
from app.fetch.collect import collect_candidates
from app.produce import run_produce
from app.report.candidates import write_candidates
from app.serve import run_server

console = Console()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def cmd_collect(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    day = args.date or _today()
    day_dir = output_dir(cfg, day)
    items = collect_candidates(cfg)
    md_path, json_path = write_candidates(day_dir, day, items)
    console.print(f"[green]候选清单已生成[/green]（{len(items)} 条）")
    console.print(f"  Markdown: {md_path}")
    console.print(f"  JSON:     {json_path}")
    console.print("下一步：复制 selection.example.json → selection.json，填写 picked 与 tone，再运行 produce")
    return 0


def cmd_produce(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_produce(cfg, day=args.date)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else None
    run_server(host=args.host, port=args.port, config_path=config_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="宠物日更：采集热点 → 选题 → 文案与素材包")
    parser.add_argument("--config", default=None, help="配置文件路径，默认 config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="抓取今日热点并生成候选清单")
    p_collect.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认今天")
    p_collect.set_defaults(func=cmd_collect)

    p_produce = sub.add_parser("produce", help="按 selection.json 生成文案并下载素材")
    p_produce.add_argument("--date", default=None, help="覆盖 selection 中的 date")
    p_produce.set_defaults(func=cmd_produce)

    p_serve = sub.add_parser("serve", help="打开本机网页：采集 / 选题 / 生成 / 看素材")
    p_serve.add_argument("--host", default="127.0.0.1", help="绑定地址，默认 127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]错误[/red] {exc}")
        return 1