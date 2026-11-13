"""Fetch original editorial photos from a news article page."""
from __future__ import annotations

from pathlib import Path
import json
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
HEADERS = {"User-Agent": "ResolveDigestScript/1.0 (+local editorial automation)"}
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


class ImageExtractionError(RuntimeError):
    pass


def _get(client, url, *, label, notify=None, referer=None):
    """Retry transient GET failures visibly; never retry cancellation callbacks."""
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if notify:
            notify(f"{label}: попытка {attempt}/{MAX_ATTEMPTS}")
        response = None
        delay = 2 ** attempt
        try:
            response = client.get(url, headers=headers, timeout=(15, 60))
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as error:
            if "CERTIFICATE_VERIFY_FAILED" in str(error).upper():
                raise ImageExtractionError(f"Ошибка проверки HTTPS-сертификата: {url}") from error
            failure = error
            reason = "Обрыв защищённого HTTPS-соединения"
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as error:
            failure = error
            reason = "Сервер не ответил вовремя или соединение прервалось"
        except requests.exceptions.HTTPError as error:
            failure = error
            status = response.status_code
            if status not in RETRY_STATUSES:
                response.close()
                if status in (401, 403):
                    raise ImageExtractionError(
                        f"Сайт отказал в доступе (HTTP {status}). Проверьте открытие статьи в браузере: {url}"
                    ) from error
                raise ImageExtractionError(f"Ошибка HTTP {status}: {url}") from error
            reason = f"Сайт временно недоступен (HTTP {status})"
            try:
                delay = min(30, max(delay, float(response.headers.get("Retry-After", 0))))
            except (TypeError, ValueError):
                pass
        except requests.exceptions.RequestException as error:
            raise ImageExtractionError(f"Ошибка загрузки: {url}: {error}") from error
        if response is not None:
            response.close()
        if attempt == MAX_ATTEMPTS:
            raise ImageExtractionError(f"{reason}. Выполнено попыток: {MAX_ATTEMPTS}.\n{url}") from failure
        print(f"Resolve Digest: {reason}; retry {attempt + 1}/{MAX_ATTEMPTS}: {url}")
        # One-second steps allow Cancel to interrupt the retry delay.
        remaining = delay
        while remaining > 0:
            if notify:
                notify(f"{reason}. Повтор {attempt + 1}/{MAX_ATTEMPTS} через {remaining:.0f} с")
            step = min(1, remaining)
            time.sleep(step)
            remaining -= step


def _client(session: requests.Session | None = None) -> requests.Session:
    """Return a session that never inherits proxy settings from the host."""
    client = session or requests.Session()
    # Equivalent to running requests with a "no proxy" flag.  Resolve can
    # inherit SOCKS_PROXY/HTTPS_PROXY from macOS or a launcher; Requests then
    # tries to load PySocks even though this script must make direct requests.
    client.trust_env = False
    return client


def _is_image_url(value: str) -> bool:
    return urlparse(value).path.lower().endswith(IMAGE_EXTENSIONS)


def _image_url(image, page_url: str) -> str | None:
    link = image.find_parent("a", href=True)
    if link:
        candidate = urljoin(page_url, link["href"])
        if _is_image_url(candidate):
            return candidate
    for attribute in ("data-original", "data-src", "data-lazy-src"):
        if image.get(attribute):
            return urljoin(page_url, image[attribute])
    picture = image.find_parent("picture")
    source = picture.find("source", srcset=True) if picture else None
    srcset = image.get("data-srcset") or image.get("srcset") or (source.get("srcset") if source else None)
    if srcset:
        def size(item):
            parts = item.strip().split()
            try:
                return float(parts[1][:-1]) if len(parts) > 1 else 0
            except ValueError:
                return 0
        return urljoin(page_url, max(srcset.split(","), key=size).strip().split()[0])
    if image.get("src"):
        return urljoin(page_url, image["src"])
    return None


def article_image_urls(article_url: str, session: requests.Session | None = None,
                       on_status=None) -> list[str]:
    """Extract editorial images from article containers, then structured metadata."""
    client = _client(session)
    response = _get(client, article_url, label="Открытие статьи", notify=on_status)
    try:
        soup = BeautifulSoup(response.text, "html.parser")
        page_url = response.url if isinstance(response.url, str) and response.url else article_url
    finally:
        response.close()
    container = None
    for selector in (".news-detail", ".news-detail__content", ".detail-text", ".news-item-detail",
                     "[itemprop='articleBody']", ".article_content", ".article-content", ".article-body", ".entry-content",
                     ".post-content", ".news-content", "article", "main", "[role='main']"):
        candidate = soup.select_one(selector)
        if candidate and candidate.find("img"):
            container = candidate
            break
    if container is None:
        heading = soup.find("h1")
        if heading:
            for parent in heading.parents:
                if parent.name in ("body", "html", "[document]"):
                    break
                if parent.find("img") and parent.find("p"):
                    container = parent
                    break

    urls: list[str] = []
    for image in container.find_all("img") if container else []:
        if image.find_parent(["nav", "header", "footer", "aside"]):
            continue
        candidate = _image_url(image, page_url)
        if candidate and urlparse(candidate).scheme in ("http", "https") and candidate not in urls:
            urls.append(candidate)
    if not urls:
        def structured_images(value):
            if isinstance(value, list):
                for item in value:
                    structured_images(item)
            elif isinstance(value, dict):
                types = value.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if any(t in ("Article", "NewsArticle", "BlogPosting", "ReportageNewsArticle") for t in types):
                    images = value.get("image", [])
                    for item in images if isinstance(images, list) else [images]:
                        raw = (item.get("url") or item.get("contentUrl")) if isinstance(item, dict) else item
                        if isinstance(raw, str):
                            candidate = urljoin(page_url, raw)
                            if urlparse(candidate).scheme in ("http", "https") and candidate not in urls:
                                urls.append(candidate)
                structured_images(value.get("@graph", []))
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                structured_images(json.loads(script.string or script.get_text()))
            except (ValueError, TypeError):
                continue
    if not urls:
        for meta in soup.select('meta[property="og:image"], meta[name="twitter:image"]'):
            candidate = urljoin(page_url, meta.get("content", ""))
            if meta.get("content") and urlparse(candidate).scheme in ("http", "https") and candidate not in urls:
                urls.append(candidate)
    if not urls:
        raise ImageExtractionError(f"Не найдены фотографии статьи (возможно, сайт загружает их через JavaScript): {article_url}")
    return urls


def download_article_image(article_url: str, photo_number: int, destination: Path,
                           session: requests.Session | None = None) -> str:
    if photo_number < 1:
        raise ImageExtractionError("Photo number must be at least 1")
    client = _client(session)
    urls = article_image_urls(article_url, client)
    if photo_number > len(urls):
        raise ImageExtractionError(
            f"Requested photo #{photo_number}, but the article contains only {len(urls)} photos: {article_url}"
        )
    image_url = urls[photo_number - 1]
    response = _get(client, image_url, label=f"Загрузка фото {photo_number}", referer=article_url)
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ImageExtractionError(f"Selected URL is not an image ({content_type}): {image_url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return image_url


def download_all_article_images(article_url: str, destination_dir: Path,
                                session: requests.Session | None = None,
                                on_progress=None, on_error=None) -> tuple[list[Path], list[str]]:
    """Download every content image as one zero-based Loader sequence.

    Each article gets its own directory so Fusion cannot combine images from
    different news items into the same numbered sequence.
    """
    client = _client(session)
    if on_progress:
        on_progress(0, 0, "Получение списка фотографий…")
    def page_status(message):
        if on_progress:
            on_progress(0, 0, message)
    urls = article_image_urls(article_url, client, on_status=page_status)
    if on_progress:
        on_progress(0, len(urls), f"Найдено фотографий: {len(urls)}")
    destination_dir.mkdir(parents=True, exist_ok=True)

    # Do not let images left by an earlier run extend the new Loader sequence.
    for stale in destination_dir.glob("photo_*.jpg"):
        if stale.is_file():
            stale.unlink()

    paths: list[Path] = []
    saved_urls: list[str] = []
    for frame, image_url in enumerate(urls, start=1):
        if on_progress:
            on_progress(frame - 1, len(urls), f"Загрузка фото {frame}/{len(urls)}")
        def image_status(message):
            if on_progress:
                on_progress(frame - 1, len(urls), message)
        try:
            response = _get(client, image_url, label=f"Загрузка фото {frame}/{len(urls)}",
                            notify=image_status, referer=article_url)
            try:
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and not content_type.startswith("image/"):
                    raise ImageExtractionError(f"Адрес вернул не изображение ({content_type}): {image_url}")
                content = response.content
                if not content:
                    raise ImageExtractionError(f"Пустой файл изображения: {image_url}")
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
            path = destination_dir / f"photo_{frame:02d}.jpg"
            path.write_bytes(content)
            paths.append(path)
            saved_urls.append(image_url)
        except (ImageExtractionError, OSError) as error:
            if on_error:
                on_error(frame, image_url, str(error))
            else:
                print(f"Не скачано фото {frame}: {image_url}: {error}")
        if on_progress:
            on_progress(frame, len(urls), f"Обработано фото {frame}/{len(urls)}; сохранено: {len(paths)}")
    return paths, saved_urls
