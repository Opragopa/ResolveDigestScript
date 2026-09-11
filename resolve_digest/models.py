from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    url: str
    photo_number: int


@dataclass(frozen=True)
class DownloadedArticle:
    article: Article
    image_path: Path
    image_url: str
