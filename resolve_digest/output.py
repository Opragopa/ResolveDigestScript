"""Resolve Digest output directory and naming helpers."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

MONTH_NAMES = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
DEFAULT_OUTPUT_ROOT = Path("Z:/Workspace")
# Digest names commonly use spaces or underscores, e.g. ``11 09`` and
# ``Daydzhest_11_09``.  A hyphen is accepted as well.
DAY_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})[\s_-]+(\d{1,2})(?!\d)")


def _creation_year(path: Path) -> int:
    stat = path.stat()
    timestamp = getattr(stat, "st_birthtime", stat.st_ctime)
    return datetime.fromtimestamp(timestamp).year


def digest_output_directory(path: Path, root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    """Build ``<root>/<year> year/<MM>_<month>/<day> <month>`` from DOCX."""
    match = DAY_MONTH_RE.search(path.stem)
    if not match:
        raise ValueError(f"Digest filename must contain day and month like '11 09': {path.name}")
    day, month = (int(value) for value in match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError(f"Invalid digest day/month in filename: {path.name}")
    year = _creation_year(path)
    month_folder = f"{month:02d}_{MONTH_NAMES[month - 1]}"
    digest_folder = f"{day:02d} {month:02d}"
    return root / f"{year} year" / "Дайджест на экраны" / month_folder / digest_folder
