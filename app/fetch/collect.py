from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from rich.console import Console

from app.config import load_sources

console = Console()

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VID_EXT = (".mp4", ".webm", ".mov", ".m3u8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(entry: dict[str, Any]) -> datetime | None:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if not parsed:
            continue
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def google_news_url(query: str, hl: str, gl: str, ceid: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={quote_plus(ceid)}"
    )


def _extract_imgs_from_html(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            urls.append(src)
    return urls


def _media_from_entry(entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []

    for link in entry.get("links") or []:
        href = link.get("href") or ""
        typ = (link.get("type") or "").lower()
        rel = (link.get("rel") or "").lower()
        if not href.startswith("http"):
            continue
        if typ.startswith("image") or any(href.lower().split("?")[0].endswith(e) for e in IMG_EXT):
            images.append(href)
        elif typ.startswith("video") or any(href.lower().split("?")[0].endswith(e) for e in VID_EXT):
            videos.append(href)
        elif rel == "enclosure" and typ.startswith("image"):
            images.append(href)

    for m in entry.get("media_content") or []:
        url = m.get("url") or ""
        typ = (m.get("type") or "").lower()
        medium = (m.get("medium") or "").lower()
        if not url.startswith("http"):
            continue
        if medium == "image" or typ.startswith("image"):
            images.append(url)
        elif medium == "video" or typ.startswith("video"):
            videos.append(url)

    for m in entry.get("media_thumbnail") or []:
        url = m.get("url") or ""
        if url.startswith("http"):
            images.append(url)

    summary = entry.get("summary") or entry.get("description") or ""
    images.extend(_extract_imgs_from_html(summary))
    content = entry.get("content")
    if isinstance(content, list):
        for c in content:
            images.extend(_extract_imgs_from_html(c.get("value") or ""))

    # 去重保序
    def uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for u in items:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    return uniq(images), uniq(videos)


def _fingerprint(title: str, link: str) -> str:
    raw = f"{(title or '').strip().lower()}|{urlparse(link).netloc}|{urlparse(link).path}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _match_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def _fetch_feed(url: str, user_agent: str, timeout: float) -> feedparser.FeedParserDict:
    headers = {"User-Agent": user_agent}
    # connect 单独限时，避免外网被墙时长时间挂死
    t = httpx.Timeout(timeout, connect=min(8.0, timeout))
    with httpx.Client(headers=headers, timeout=t, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return feedparser.parse(resp.content)


def _take_diverse(sorted_items: list[dict[str, Any]], n: int, cap: int) -> list[dict[str, Any]]:
    """按已排序顺序取 n 条，同一信源先不超过 cap，不够再回头补。"""
    picked: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []
    for it in sorted_items:
        sid = str(it.get("source_id") or "")
        if counts.get(sid, 0) >= cap:
            deferred.append(it)
            continue
        picked.append(it)
        counts[sid] = counts.get(sid, 0) + 1
        if len(picked) >= n:
            return picked
    for it in deferred:
        if len(picked) >= n:
            break
        picked.append(it)
    return picked


def collect_candidates(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    collect_cfg = cfg.get("collect") or {}
    lookback = int(collect_cfg.get("lookback_hours", 48))
    max_per_source = int(collect_cfg.get("max_per_source", 15))
    max_candidates = int(collect_cfg.get("max_candidates", 20))
    include_kw = collect_cfg.get("include_keywords") or []
    conflict_kw = collect_cfg.get("conflict_keywords") or []
    warm_kw = collect_cfg.get("warm_keywords") or []
    exclude_kw = collect_cfg.get("exclude_keywords") or []
    balance_tracks = bool(collect_cfg.get("balance_tracks", True))
    net = cfg.get("network") or {}
    user_agent = net.get("user_agent") or "PetDailyBot/0.1"
    timeout = float(net.get("timeout_seconds") or 30)

    cutoff = _now() - timedelta(hours=lookback)
    sources = load_sources()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_titles: set[str] = set()

    for src in sources:
        src_id = src.get("id") or "unknown"
        name = src.get("name") or src_id
        track = (src.get("track") or "any").strip().lower()
        typ = src.get("type") or "rss"
        if typ == "google_news":
            url = google_news_url(
                src.get("query") or "宠物",
                src.get("hl") or "zh-CN",
                src.get("gl") or "CN",
                src.get("ceid") or "CN:zh-Hans",
            )
        else:
            url = src.get("url")
            if not url:
                console.print(f"[yellow]跳过无 URL 信源: {src_id}[/yellow]")
                continue

        console.print(f"[cyan]抓取[/cyan] {name} ...")
        try:
            feed = _fetch_feed(url, user_agent, timeout)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]失败[/red] {name}: {exc}")
            continue

        count = 0
        for entry in feed.entries:
            if count >= max_per_source:
                break
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            dt = _parse_dt(entry)
            if dt and dt < cutoff:
                continue

            summary = BeautifulSoup(
                entry.get("summary") or entry.get("description") or "",
                "lxml",
            ).get_text(" ", strip=True)
            summary = re.sub(r"\s+", " ", summary)[:280]

            blob = f"{title} {summary}"
            if not _match_keywords(blob, include_kw):
                continue
            src_lang = (src.get("lang") or ("zh" if typ == "google_news" else "unknown")).lower()
            if track == "conflict" and conflict_kw and not _match_keywords(blob, conflict_kw):
                continue
            # 英文温馨源本身偏生活向，不再强制中文暖词
            if track == "warm" and warm_kw and src_lang != "en" and not _match_keywords(blob, warm_kw):
                continue
            if _match_keywords(blob, exclude_kw):
                continue

            fp = _fingerprint(title, link)
            if fp in seen:
                continue
            # 同源多转载：标题去媒体后缀后去重
            title_key = re.sub(r"\s*[-_|｜].*$", "", title).strip().lower()
            title_key = re.sub(r"\s+", "", title_key)[:40]
            if title_key and title_key in seen_titles:
                continue
            seen.add(fp)
            if title_key:
                seen_titles.add(title_key)

            score_kw = conflict_kw if track == "conflict" else warm_kw
            track_score = sum(1 for k in score_kw if k.lower() in blob.lower()) if score_kw else 0
            images, videos = _media_from_entry(entry)
            items.append(
                {
                    "fingerprint": fp,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published_at": dt.isoformat() if dt else None,
                    "source_id": src_id,
                    "source_name": name,
                    "track": track,
                    "lang": src.get("lang") or ("zh" if typ == "google_news" else "unknown"),
                    "images": images,
                    "videos": videos,
                    "has_image": bool(images),
                    "has_video": bool(videos),
                    "track_score": track_score,
                }
            )
            count += 1

        console.print(f"  → 纳入 {count} 条")

    def sort_key(it: dict[str, Any]) -> tuple:
        ts = it.get("published_at") or ""
        media_score = int(it.get("has_image")) + 2 * int(it.get("has_video"))
        return (int(it.get("track_score") or 0), ts, media_score)

    if balance_tracks:
        conflict_items = sorted(
            [it for it in items if it.get("track") == "conflict"],
            key=sort_key,
            reverse=True,
        )
        warm_items = sorted(
            [it for it in items if it.get("track") == "warm"],
            key=sort_key,
            reverse=True,
        )
        other_items = sorted(
            [it for it in items if it.get("track") not in {"conflict", "warm"}],
            key=sort_key,
            reverse=True,
        )
        half = max(1, max_candidates // 2)
        # 温馨轨信源多（Reddit 更新快），每源先最多 2 条，避免挤掉 Dodo / PetMD
        warm_picked = _take_diverse(warm_items, half, cap=2)
        picked: list[dict[str, Any]] = []
        picked.extend(conflict_items[:half])
        picked.extend(warm_picked)
        warm_picked_ids = {id(it) for it in warm_picked}
        # 某一轨不足时用另一轨/其它补满
        remainder = (
            conflict_items[half:]
            + [it for it in warm_items if id(it) not in warm_picked_ids]
            + other_items
        )
        for it in remainder:
            if len(picked) >= max_candidates:
                break
            if it in picked:
                continue
            picked.append(it)
        items = picked[:max_candidates]
        # 展示：冲突在前、温馨在后，各自内按分数
        items = sorted(
            items,
            key=lambda it: (
                0 if it.get("track") == "conflict" else 1 if it.get("track") == "warm" else 2,
                -int(it.get("track_score") or 0),
                it.get("published_at") or "",
            ),
        )
    else:
        items.sort(key=sort_key, reverse=True)
        items = items[:max_candidates]

    for i, it in enumerate(items, start=1):
        it["id"] = i
    return items
