from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from rich.console import Console

from app.media.extract import extract_media_from_url

console = Console()


def _ext_from_url_or_ct(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}:
        return suffix
    if content_type:
        guess = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guess:
            return guess
    return ".bin"


def _download_urls(
    client: httpx.Client,
    urls: list[str],
    item_dir: Path,
    prefix: str,
    limit: int,
) -> list[str]:
    saved: list[str] = []
    for idx, url in enumerate(urls[:limit], start=1):
        if url.lower().endswith(".m3u8"):
            console.print(f"[yellow]跳过 m3u8[/yellow] {url}")
            continue
        try:
            resp = client.get(url)
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            # 误下到 HTML / SVG 时跳过
            if "text/html" in ctype or "svg" in ctype:
                console.print(f"[yellow]跳过非位图媒体[/yellow] {url}")
                continue
            if prefix == "image" and ctype and not ctype.startswith("image/"):
                console.print(f"[yellow]跳过非图片 Content-Type[/yellow] {ctype} {url}")
                continue
            ext = _ext_from_url_or_ct(url, ctype)
            dest = item_dir / f"{prefix}_{idx}{ext}"
            dest.write_bytes(resp.content)
            saved.append(str(dest))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]{prefix}下载失败[/yellow] {url}: {exc}")
    return saved


def download_media_for_items(
    items: list[dict[str, Any]],
    media_dir: Path,
    user_agent: str,
    timeout: float,
) -> list[dict[str, Any]]:
    media_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    headers = {"User-Agent": user_agent}

    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        for it in items:
            item_id = it["id"]
            item_dir = media_dir / f"item_{item_id:02d}"
            item_dir.mkdir(parents=True, exist_ok=True)

            image_urls = list(it.get("images") or [])
            video_urls = list(it.get("videos") or [])
            source_page: str | None = None

            # RSS 无媒体时，打开原文用 trafilatura + HTML 元数据抽图
            if not image_urls and not video_urls and it.get("link"):
                console.print(f"[cyan]回源抽媒体[/cyan] [{item_id}] …")
                scraped_imgs, scraped_vids, source_page = extract_media_from_url(
                    str(it["link"]),
                    user_agent=user_agent,
                    timeout=timeout,
                    client=client,
                )
                image_urls = scraped_imgs
                video_urls = scraped_vids
                if image_urls or video_urls:
                    console.print(
                        f"  → 抽到 图 {len(image_urls)} / 视频 {len(video_urls)}"
                        + (f"（{source_page}）" if source_page else "")
                    )
                else:
                    console.print("  → 原文未抽到可用媒体")

            downloaded_images = _download_urls(client, image_urls, item_dir, "image", 5)
            downloaded_videos = _download_urls(client, video_urls, item_dir, "video", 2)

            # RSS 有链但下载全失败时，再试一次原文
            if not downloaded_images and not downloaded_videos and it.get("link") and (
                it.get("images") or it.get("videos")
            ):
                console.print(f"[cyan]RSS 媒体失败，回源重试[/cyan] [{item_id}] …")
                scraped_imgs, scraped_vids, source_page = extract_media_from_url(
                    str(it["link"]),
                    user_agent=user_agent,
                    timeout=timeout,
                    client=client,
                )
                downloaded_images = _download_urls(client, scraped_imgs, item_dir, "image", 5)
                downloaded_videos = _download_urls(client, scraped_vids, item_dir, "video", 2)

            missing = not (downloaded_images or downloaded_videos)
            placeholder = item_dir / "NEED_MANUAL_MEDIA.txt"
            if missing:
                note = (
                    "该条目未能自动下载到可用图片/视频，请自行放入本目录后用于成片。\n"
                    f"原链接：{it.get('link')}\n"
                )
                if source_page and source_page != it.get("link"):
                    note += f"解析后页面：{source_page}\n"
                placeholder.write_text(note, encoding="utf-8")
            elif placeholder.exists():
                placeholder.unlink()

            results.append(
                {
                    "id": item_id,
                    "title": it.get("title"),
                    "dir": str(item_dir),
                    "images": downloaded_images,
                    "videos": downloaded_videos,
                    "need_manual": missing,
                    "source_page": source_page,
                }
            )
    return results
