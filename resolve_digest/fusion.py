"""Narrow adapter around Resolve's scripting API; easy to test without Resolve."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .models import DownloadedArticle


class ResolveUpdateError(RuntimeError):
    pass


def _resolve_api():
    """Import Resolve's API in both a normal Python shell and its menu runner."""
    try:
        import DaVinciResolveScript as dvr
        return dvr
    except ImportError:
        # Resolve does not set PYTHONPATH for every Workspace > Scripts launch
        # on Windows.  Its documented scripting module directory is stable.
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        modules = program_data / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Developer" / "Scripting" / "Modules"
        if str(modules) not in sys.path:
            sys.path.insert(0, str(modules))
        try:
            import DaVinciResolveScript as dvr
            return dvr
        except ImportError as error:
            raise ResolveUpdateError(
                "Resolve API module was not found. Run this from DaVinci Resolve's Workspace > Scripts menu."
            ) from error


def _find_required(comp, node_name: str):
    node = comp.FindTool(node_name)
    if not node:
        raise ResolveUpdateError(f"Fusion node not found: {node_name}")
    return node


def update_composition(comp, articles: list[DownloadedArticle]) -> None:
    """Replace six reserved node groups, leaving the Fusion graph untouched."""
    comp.Lock()
    try:
        for index, item in enumerate(articles, start=1):
            suffix = f"{index:02d}"
            _find_required(comp, f"title_{suffix}").SetInput("StyledText", item.article.title)
            _find_required(comp, f"body_{suffix}").SetInput("StyledText", item.article.body)
            _find_required(comp, f"image_{suffix}").SetInput("Clip", str(Path(item.image_path).resolve()))
    finally:
        comp.Unlock()


def current_timeline_composition(clip_name: str | None = None):
    dvr = _resolve_api()
    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject() if resolve else None
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        raise ResolveUpdateError("Open the target Resolve project and timeline first.")
    clips = timeline.GetItemListInTrack("video", 1) or []
    if clip_name:
        clips = [clip for clip in clips if clip.GetName() == clip_name]
    for clip in clips:
        comp = clip.GetFusionCompByIndex(1)
        if comp:
            return comp
    selector = f" named '{clip_name}'" if clip_name else ""
    raise ResolveUpdateError(f"No Fusion composition found on video track 1{selector}.")
