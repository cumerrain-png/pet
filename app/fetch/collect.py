from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

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


def _on_local_day(dt: datetime, now: datetime, tz_name: str) -> bool:
    tz = ZoneInfo(tz_name)
    return dt.astimezone(tz).date() == now.astimezone(tz).date()


def _source_url(src: dict[str, Any]) -> str | None:
    if (src.get("type") or "rss") == "google_news":
        return google_news_url(
            src.get("query") or "宠物",
            src.get("hl") or "zh-CN",
            src.get("gl") or "CN",
            src.get("ceid") or "CN:zh-Hans",
        )
    return src.get("url") or None


def _fetch_one(
    src: dict[str, Any], user_agent: str, timeout: float
) -> tuple[dict[str, Any], feedparser.FeedParserDict | None, str | None]:
    url = _source_url(src)
    if not url:
        return src, None, "无 URL"
    try:
        return src, _fetch_feed(url, user_agent, timeout), None
    except Exception as exc:  # noqa: BLE001
        return src, None, str(exc)


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


# 短词（猫/狗/cat/pet）误伤很多，先丢掉明显不是宠物的撞词，再要求正文像宠物内容。
_REJECT_RE = re.compile(
    r"貓空|猫空|黑貓中隊|黑猫中队|四叉貓|四叉猫|熊猫|熊貓|猫头鹰|貓頭鷹|热狗|熱狗|"
    r"狗狗币|狗狗幣|dogecoin|"
    r"\bcat\s*\.?\s*[1-5]\b|\bhurricane\b|\bCAT\s*20\d{2}\b|\bCAT\d{6}|"
    r"ASX:\s*PET|PET SHOP BOYS|Pet Shop Boys|\bCat Empire\b|"
    r"\bcopycat\b|\bcatalog|\bcatalyst|\bcaterpill|\bdogwood\b|"
    r"\bunderdog\b|\bwatchdog\b|\bhot\s*dogs?\b|"
    r"hardwood|softwood|fuelwood|first dog on the moon|\bdog squad\b|"
    r"早期アクセス|オープンワールド|連載|試し読み|"
    r"\bPET\s*scans?\b|ASX:\s*CAT\b|"
    r"除息|填息|商标|商標|购标|購標|"
    r"黑貓裝置|黑猫装置|50隻黑貓|50只黑猫|"
    r"for global buyers",
    re.IGNORECASE,
)
_PET_RE = re.compile(
    r"宠物|寵物|猫咪|貓咪|狗狗|小猫|小狗|小貓|流浪猫|流浪狗|流浪貓|流浪狗|"
    r"毛孩子|毛小孩|铲屎|养宠|養寵|喵星人|汪星人|猫粮|狗粮|貓糧|狗糧|"
    r"领养|領養|绝育|絕育|猫咖|貓咖|柯基|金毛|哈士奇|布偶|"
    r"猫|狗|貓|犬|"
    r"\bpets?\b|\bdogs?\b|\bcats?\b|\bpupp(?:y|ies)\b|\bkittens?\b|"
    r"\bcanines?\b|\bfelines?\b|\bpooches?\b|\bkitt(?:y|ies)\b|"
    r"ペット|わんこ|にゃんこ|子猫|子犬|飼い猫|飼い犬|保護犬|保護猫|犬猫|譲渡|"
    r"반려동물|강아지|고양이|반려견|반려묘|길고양이",
    re.IGNORECASE,
)


def _is_pet_topic(text: str) -> bool:
    if _REJECT_RE.search(text):
        return False
    return _PET_RE.search(text) is not None


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
    conflict_kw = collect_cfg.get("conflict_keywords") or []
    warm_kw = collect_cfg.get("warm_keywords") or []
    exclude_kw = collect_cfg.get("exclude_keywords") or []
    balance_tracks = bool(collect_cfg.get("balance_tracks", True))
    same_day_only = bool(collect_cfg.get("same_day_only", False))
    tz_name = str(collect_cfg.get("timezone") or "Asia/Shanghai")
    diverse_cap = max(1, int(collect_cfg.get("diverse_per_source", 8)))
    workers = max(1, int(collect_cfg.get("fetch_workers", 6)))
    net = cfg.get("network") or {}
    user_agent = net.get("user_agent") or "PetDailyBot/0.1"
    timeout = float(net.get("timeout_seconds") or 30)

    now = _now()
    cutoff = now - timedelta(hours=lookback)
    sources = load_sources()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_titles: set[str] = set()

    def _in_window(dt: datetime | None) -> bool:
        if same_day_only:
            if dt is None:
                return False
            return _on_local_day(dt, now, tz_name)
        return not (dt and dt < cutoff)

    console.print(f"[cyan]并行抓取 {len(sources)} 个信源[/cyan] ...")
    feeds: dict[int, feedparser.FeedParserDict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_one, src, user_agent, timeout) for src in sources]
        for fut in as_completed(futures):
            src, feed, err = fut.result()
            name = src.get("name") or src.get("id") or "unknown"
            if err or feed is None:
                console.print(f"[red]失败[/red] {name}: {err}")
                continue
            feeds[id(src)] = feed
            console.print(f"[cyan]完成[/cyan] {name}（{len(feed.entries)} 条原始）")

    for src in sources:
        feed = feeds.get(id(src))
        if feed is None:
            continue
        src_id = src.get("id") or "unknown"
        name = src.get("name") or src_id
        track = (src.get("track") or "any").strip().lower()
        typ = src.get("type") or "rss"

        count = 0
        for entry in feed.entries:
            if count >= max_per_source:
                break
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            dt = _parse_dt(entry)
            if not _in_window(dt):
                continue

            summary = BeautifulSoup(
                entry.get("summary") or entry.get("description") or "",
                "lxml",
            ).get_text(" ", strip=True)
            summary = re.sub(r"\s+", " ", summary)[:280]

            blob = f"{title} {summary}"
            if not _is_pet_topic(blob):
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
        # 当天广覆盖：先按时间从新到旧，每个信源设上限，不够再补
        items.sort(key=lambda it: it.get("published_at") or "", reverse=True)
        raw_count = len(items)
        items = _take_diverse(items, max_candidates, diverse_cap)
        items.sort(key=lambda it: it.get("published_at") or "", reverse=True)
        day_note = "当天" if same_day_only else f"近 {lookback} 小时"
        console.print(
            f"[green]{day_note}去重后 {raw_count} 条，输出 {len(items)} 条[/green]"
            f"（目标 {max_candidates}）"
        )

    for i, it in enumerate(items, start=1):
        it["id"] = i
    return items
