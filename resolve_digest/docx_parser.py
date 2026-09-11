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
PHOTO_RE = re.compile(r"\(\s*(?:фото|photo)\s*№?\s*(\d+)\s*\)", re.IGNORECASE)


class DocumentFormatError(ValueError):
    pass


def _clean(text: str) -> str:
    return " ".join(text.split())


def parse_docx(path: Path, expected_count: int = 6) -> list[Article]:
    """Return articles in document order, rejecting ambiguous/incomplete input."""
    document = Document(str(path))
    paragraphs = [_clean(p.text) for p in document.paragraphs]
    paragraphs = [p for p in paragraphs if p]
    articles: list[Article] = []
    pending: list[str] = []

    for paragraph in paragraphs:
        url_match = URL_RE.search(paragraph)
        photo_match = PHOTO_RE.search(paragraph)
        if not url_match:
            pending.append(paragraph)
            continue
        if not photo_match:
            raise DocumentFormatError(
                f"Found an article URL without '(фото N)': {url_match.group(0)}"
            )
        if not pending:
            raise DocumentFormatError(f"No title before URL: {url_match.group(0)}")

        title, *body_paragraphs = pending
        body = "\n".join(body_paragraphs).strip()
        if not body:
            raise DocumentFormatError(f"No body text for: {title}")
        articles.append(Article(title, body, url_match.group(0), int(photo_match.group(1))))
        pending = []

    if pending:
        raise DocumentFormatError("Text after the last news block has no URL and photo marker")
    if len(articles) != expected_count:
        raise DocumentFormatError(f"Expected exactly {expected_count} news items, found {len(articles)}")
    return articles
