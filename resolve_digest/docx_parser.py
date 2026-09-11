"""Parsing of the editorial DOCX source.

Expected repeating block: title, one or more body paragraphs, article URL and
``(фото N)``.  The URL and photo marker may be on the same paragraph.
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from .models import Article

URL_RE = re.compile(r"https?://[^\s)>]+", re.IGNORECASE)
# Editorial documents have appeared in all of these forms: `(фото 2)`,
# `Фото №2`, and `photo 2`.  Word often also moves that line before the URL.
PHOTO_RE = re.compile(r"(?:\(\s*)?\b(?:фото|photo)\s*(?:№|N|#)?\s*(\d+)\b\s*\)?", re.IGNORECASE)


class DocumentFormatError(ValueError):
    pass


def _clean(text: str) -> str:
    return " ".join(text.split())


def parse_docx(path: Path, expected_count: int = 5) -> list[Article]:
    """Return articles in document order, rejecting ambiguous/incomplete input."""
    document = Document(str(path))
    paragraphs = [_clean(p.text) for p in document.paragraphs]
    paragraphs = [p for p in paragraphs if p]
    articles: list[Article] = []
    pending: list[str] = []
    pending_url: str | None = None
    pending_photo_number: int | None = None
    after_url: list[str] = []

    def add_article(url: str, photo_number: int) -> None:
        nonlocal pending, pending_photo_number
        if not pending:
            raise DocumentFormatError(f"No title before URL: {url}")
        # Marker-only paragraphs are metadata, never part of the description.
        content = [_clean(PHOTO_RE.sub("", text)) for text in pending]
        content = [text for text in content if text]
        if not content:
            raise DocumentFormatError(f"No title before URL: {url}")
        title, *body_paragraphs = content
        body = "\n".join(body_paragraphs).strip()
        if not body:
            raise DocumentFormatError(f"No body text for: {title}")
        articles.append(Article(title, body, url, photo_number))
        pending = []
        pending_photo_number = None

    for paragraph in paragraphs:
        url_match = URL_RE.search(paragraph)
        photo_match = PHOTO_RE.search(paragraph)
        if pending_url:
            # Allow captions/empty editor lines between a URL and the marker.
            # A second URL proves the prior news block is incomplete.
            if url_match:
                # The document author omitted a marker for the preceding item.
                # Finalize it with the agreed default; text encountered after
                # that URL belongs to the next item and must be retained.
                add_article(pending_url, 1)
                pending = after_url
                after_url = []
                pending_url = None
            else:
                if photo_match:
                    add_article(pending_url, int(photo_match.group(1)))
                    after_url = []
                    pending_url = None
                else:
                    after_url.append(paragraph)
                continue
        if not url_match:
            pending.append(paragraph)
            if photo_match:
                pending_photo_number = int(photo_match.group(1))
            continue
        if photo_match:
            add_article(url_match.group(0), int(photo_match.group(1)))
        elif pending_photo_number is not None:
            # The marker is commonly written immediately before the source URL.
            add_article(url_match.group(0), pending_photo_number)
        else:
            pending_url = url_match.group(0)

    if pending_url:
        # A final article can end immediately after its source URL.
        add_article(pending_url, 1)
    if pending:
        raise DocumentFormatError("Text after the last news block has no URL and photo marker")
    if len(articles) != expected_count:
        raise DocumentFormatError(f"Expected exactly {expected_count} news items, found {len(articles)}")
    return articles
