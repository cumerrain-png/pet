from __future__ import annotations

import json
import mimetypes
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.config import ROOT, load_config, output_dir, selection_path
from app.fetch.collect import collect_candidates
from app.produce import run_produce
from app.report.candidates import write_candidates

WEB_DIR = ROOT / "web"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _json_bytes(data: Any, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _list_media_files(item_dir: Path) -> dict[str, list[str]]:
    images: list[str] = []
    videos: list[str] = []
    if not item_dir.is_dir():
        return {"images": images, "videos": videos}
    for p in sorted(item_dir.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        rel = f"{item_dir.name}/{p.name}"
        if ext in IMAGE_EXTS:
            images.append(rel)
        elif ext in VIDEO_EXTS:
            videos.append(rel)
    return {"images": images, "videos": videos}


def _enrich_items(day_dir: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    media_root = day_dir / "media"
    for it in items:
        row = dict(it)
        item_id = int(it["id"])
        item_dir = media_root / f"item_{item_id:02d}"
        files = _list_media_files(item_dir)
        row["local_images"] = files["images"]
        row["local_videos"] = files["videos"]
        row["need_manual"] = (item_dir / "NEED_MANUAL_MEDIA.txt").exists() and not (
            files["images"] or files["videos"]
        )
        out.append(row)
    return out


def _day_status(cfg: dict[str, Any]) -> dict[str, Any]:
    day = _today()
    day_dir = output_dir(cfg, day)
    candidates_path = day_dir / "candidates.json"
    has_candidates = candidates_path.exists()
    has_result = (day_dir / "script_douyin.txt").exists()
    count = 0
    if has_candidates:
        try:
            data = json.loads(candidates_path.read_text(encoding="utf-8"))
            count = len(data.get("items") or [])
        except (OSError, json.JSONDecodeError):
            count = 0
    return {
        "date": day,
        "has_candidates": has_candidates,
        "candidate_count": count,
        "has_result": has_result,
    }


def _handle_api(method: str, path: str, body: bytes, cfg: dict[str, Any]) -> tuple[int, bytes, str]:
    if path == "/api/today" and method == "GET":
        return _json_bytes(_day_status(cfg))

    if path == "/api/candidates" and method == "GET":
        day = _today()
        day_dir = output_dir(cfg, day)
        cpath = day_dir / "candidates.json"
        if not cpath.exists():
            return _json_bytes({"date": day, "items": [], "message": "尚无候选，请先采集"}, 200)
        data = json.loads(cpath.read_text(encoding="utf-8"))
        items = _enrich_items(day_dir, list(data.get("items") or []))
        return _json_bytes({"date": day, "items": items})

    if path == "/api/collect" and method == "POST":
        day = _today()
        day_dir = output_dir(cfg, day)
        items = collect_candidates(cfg)
        write_candidates(day_dir, day, items)
        enriched = _enrich_items(day_dir, items)
        return _json_bytes({"ok": True, "date": day, "count": len(enriched), "items": enriched})

    if path == "/api/produce" and method == "POST":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return _json_bytes({"ok": False, "error": "请求体不是合法 JSON"}, 400)
        picked = payload.get("picked") or []
        if not picked:
            return _json_bytes({"ok": False, "error": "请至少选择一条新闻"}, 400)
        day = _today()
        selection = {
            "date": day,
            "picked": [int(x) for x in picked],
            "tone": str(payload.get("tone") or ""),
            "duration": str(payload.get("duration") or "45s"),
            "extra_notes": str(payload.get("extra_notes") or ""),
        }
        sel_path = selection_path(cfg)
        sel_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        day_dir = run_produce(cfg, day=day)
        return _json_bytes({"ok": True, "date": day, "dir": str(day_dir), **_result_payload(day_dir)})

    if path == "/api/result" and method == "GET":
        day = _today()
        day_dir = output_dir(cfg, day)
        if not (day_dir / "script_douyin.txt").exists():
            return _json_bytes({"date": day, "has_result": False}, 200)
        return _json_bytes({"date": day, "has_result": True, **_result_payload(day_dir)})

    return _json_bytes({"error": "未找到接口"}, 404)


def _result_payload(day_dir: Path) -> dict[str, Any]:
    media_manifest: list[dict[str, Any]] = []
    sources_path = day_dir / "sources.json"
    if sources_path.exists():
        try:
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
            for m in sources.get("media") or []:
                item_id = int(m["id"])
                files = _list_media_files(day_dir / "media" / f"item_{item_id:02d}")
                media_manifest.append(
                    {
                        "id": item_id,
                        "title": m.get("title"),
                        "need_manual": bool(m.get("need_manual")),
                        "local_images": files["images"],
                        "local_videos": files["videos"],
                    }
                )
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            media_manifest = []
    return {
        "script_douyin": _read_text(day_dir / "script_douyin.txt"),
        "note_xhs": _read_text(day_dir / "note_xhs.md"),
        "media": media_manifest,
    }


def _safe_media_file(day_dir: Path, rel: str) -> Path | None:
    media_root = (day_dir / "media").resolve()
    # rel like item_01/image_1.jpg
    candidate = (media_root / Path(rel)).resolve()
    try:
        candidate.relative_to(media_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def make_handler(cfg: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "PetDailyServe/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[serve] {self.address_string()} {fmt % args}")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            if path.startswith("/api/"):
                try:
                    status, body, ctype = _handle_api("GET", path, b"", cfg)
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    status, body, ctype = _json_bytes({"ok": False, "error": str(exc)}, 500)
                self._send(status, body, ctype)
                return

            if path.startswith("/media/"):
                day_dir = output_dir(cfg, _today())
                rel = path[len("/media/") :]
                file_path = _safe_media_file(day_dir, rel)
                if not file_path:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
                    return
                data = file_path.read_bytes()
                ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                self._send(200, data, ctype)
                return

            # static
            rel = "index.html" if path in {"", "/"} else path.lstrip("/")
            file_path = (WEB_DIR / rel).resolve()
            try:
                file_path.relative_to(WEB_DIR.resolve())
            except ValueError:
                self._send(403, b"Forbidden", "text/plain; charset=utf-8")
                return
            if not file_path.is_file():
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            data = file_path.read_bytes()
            ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
                ctype = f"{ctype}; charset=utf-8"
            self._send(200, data, ctype)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            body = self._read_body()
            if not path.startswith("/api/"):
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            try:
                status, resp, ctype = _handle_api("POST", path, body, cfg)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                status, resp, ctype = _json_bytes({"ok": False, "error": str(exc)}, 500)
            self._send(status, resp, ctype)

    return Handler


def run_server(host: str = "127.0.0.1", port: int = 8765, config_path: Path | None = None) -> None:
    cfg = load_config(config_path)
    if not WEB_DIR.is_dir():
        raise FileNotFoundError(f"未找到前端目录: {WEB_DIR}")
    handler = make_handler(cfg)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Pet Daily 本机页: http://{host}:{port}/", flush=True)
    print("按 Ctrl+C 停止", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
