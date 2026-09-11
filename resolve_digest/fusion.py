"""Narrow adapter around Resolve's scripting API; easy to test without Resolve."""
from __future__ import annotations

from pathlib import Path

from .models import DownloadedArticle


class ResolveUpdateError(RuntimeError):
    pass


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
    try:
        import DaVinciResolveScript as dvr
    except ImportError as error:
        raise ResolveUpdateError("Run with DaVinci Resolve's bundled Python interpreter/API.") from error
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
