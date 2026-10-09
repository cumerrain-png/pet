from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 根节点必须是对象: {path}")
    return data


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or (ROOT / "config.yaml")
    cfg = load_yaml(path)
    cfg["_root"] = str(ROOT)
    cfg["_config_path"] = str(path)
    return cfg


def load_sources(sources_path: Path | None = None) -> list[dict[str, Any]]:
    path = sources_path or (ROOT / "data" / "sources.yaml")
    data = load_yaml(path)
    sources = data.get("sources") or []
    return [s for s in sources if s.get("enabled", True)]


def output_dir(cfg: dict[str, Any], day: str) -> Path:
    base = Path(cfg["paths"]["output_dir"])
    if not base.is_absolute():
        base = ROOT / base
    path = base / day
    path.mkdir(parents=True, exist_ok=True)
    return path


def selection_path(cfg: dict[str, Any]) -> Path:
    p = Path(cfg["paths"]["selection_file"])
    if not p.is_absolute():
        p = ROOT / p
    return p