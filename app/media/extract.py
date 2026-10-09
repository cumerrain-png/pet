from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from rich.console import Console

console = Console()

VID_EXT = (".mp4", ".webm", ".mov")
SKIP_IMG_HINTS = (
    "logo",
    "icon",
    "sprite",
    "avatar",
    "emoji",
    "pixel",
    "1x1",
    "spacer",
    "badge",
    "button",
    "share-",
    "tracking",
    "adservice",
    "doubleclick",
    "favicon",
    ".svg",
)


def _is_http(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _looks_like_video(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in VID_EXT)


def _bad_asset(url: str) -> bool:
    lower = url.lower()
    return any(h in lower for h in SKIP_IMG_HINTS)


def _uniq(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _meta_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    for key, val in (
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
        ("itemprop", "image"),
    ):
        for tag in soup.find_all("meta", attrs={key: val}):
            content = (tag.get("content") or "").strip()
            if content:
                urls.append(urljoin(base_url, content))
    link = soup.find("link", attrs={"rel": "image_src"})
    if link and link.get("href"):
        urls.append(urljoin(base_url, link["href"]))
    return urls


def _html_media(soup: BeautifulSoup, base_url: str) -> tuple[list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            srcset = img.get("srcset") or ""
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        if not src:
            continue
        url = urljoin(base_url, src.strip())
        if _is_http(url) and not _bad_asset(url):
            images.append(url)

    for video in soup.find_all("video"):
        src = video.get("src")
        if src:
            url = urljoin(base_url, src.strip())
            if _is_http(url):
                videos.append(url)
        poster = video.get("poster")
        if poster:
            images.append(urljoin(base_url, poster.strip()))
        for source in video.find_all("source"):
            src = source.get("src")
            if not src:
                continue
            url = urljoin(base_url, src.strip())
            if _is_http(url) and _looks_like_video(url):
                videos.append(url)

    return images, videos


def extract_media_from_html(html: str, base_url: str) -> tuple[list[str], list[str]]:
    if not html:
        return [], []
    soup = BeautifulSoup(html, "lxml")
    images = _meta_images(soup, base_url)
    body_imgs, videos = _html_media(soup, base_url)
    images.extend(body_imgs)

    for m in re.finditer(
        r'(?:src|content)=["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp|gif)[^"\']*)["\']',
        html,
        re.I,
    ):
        images.append(m.group(1))

    images = [u for u in _uniq(images) if not _bad_asset(u)]
    videos = [u for u in _uniq(videos) if not u.lower().endswith(".m3u8")]
    return images[:8], videos[:3]


def _trafilatura_image(html: str, page_url: str) -> str | None:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        doc = trafilatura.bare_extraction(
            html,
            url=page_url,
            include_images=True,
            with_metadata=True,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]trafilatura 解析失败[/yellow] {page_url}: {exc}")
        return None
    if not doc:
        return None
    img = getattr(doc, "image", None)
    if not img and hasattr(doc, "as_dict"):
        try:
            img = (doc.as_dict() or {}).get("image")
        except Exception:  # noqa: BLE001
            img = None
    return img if isinstance(img, str) and _is_http(img) else None


def extract_media_from_url(
    url: str,
    user_agent: str,
    timeout: float,
    client: httpx.Client | None = None,
) -> tuple[list[str], list[str], str | None]:
    """打开原文页抽取图片/视频直链。返回 (images, videos, final_url)。"""
    if not url or not _is_http(url):
        return [], [], None

    def _extract_with(cli: httpx.Client) -> tuple[list[str], list[str], str | None]:
        try:
            resp = cli.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]打开原文失败[/yellow] {url}: {exc}")
            return [], [], None
        final_url = str(resp.url)
        html = resp.text
        meta_img = _trafilatura_image(html, final_url)
        page_images, page_videos = extract_media_from_html(html, final_url)
        images = _uniq(([meta_img] if meta_img else []) + page_images)
        images = [u for u in images if not _bad_asset(u)][:8]
        videos = [u for u in page_videos if not u.lower().endswith(".m3u8")][:3]
        return images, videos, final_url

    if client is not None:
        return _extract_with(client)

    with httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        follow_redirects=True,
    ) as cli:
        return _extract_with(cli)
