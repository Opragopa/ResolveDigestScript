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
    """Replace five reserved node groups, leaving the Fusion graph untouched."""
    comp.Lock()
    try:
        for index, item in enumerate(articles, start=1):
            suffix = f"{index:02d}"
            # Keep each article's title/body/photo bound to the same numeric
            # slot.  Uppercase is intentional for the on-screen title style.
            _find_required(comp, f"title_{suffix}").SetInput("StyledText", item.article.title.upper())
            _find_required(comp, f"body_{suffix}").SetInput("StyledText", item.article.body)
            _find_required(comp, f"image_{suffix}").SetInput("Clip", str(Path(item.image_path).resolve()))
    finally:
        comp.Unlock()


def current_project():
    dvr = _resolve_api()
    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject() if resolve else None
    if not project:
        raise ResolveUpdateError("Open the target Resolve project first.")
    return project


def _load_render_preset(project, requested_name: str) -> str:
    """Load a preset, tolerating Resolve's case/whitespace differences."""
    names = [requested_name]
    get_presets = getattr(project, "GetRenderPresetList", None)
    if callable(get_presets):
        available = get_presets() or []
        wanted = requested_name.casefold().strip()
        names.extend(
            name for name in available
            if isinstance(name, str) and name.casefold().strip() == wanted and name not in names
        )
    for name in names:
        # Some Resolve versions return None on success; only an explicit
        # False means that the preset could not be loaded.
        if project.LoadRenderPreset(name) is not False:
            return name
    raise ResolveUpdateError(f"Render preset not found: {requested_name}")


def render_current_timeline(output_dir: Path, preset_name: str) -> None:
    """Load a render preset and start a job for the current timeline."""
    project = current_project()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise ResolveUpdateError("Open the target Resolve project and timeline first.")
    output_dir.mkdir(parents=True, exist_ok=True)
    _load_render_preset(project, preset_name)
    if project.SetRenderSettings({"TargetDir": str(output_dir)}) is False:
        raise ResolveUpdateError(f"Could not set render output directory: {output_dir}")
    job_id = project.AddRenderJob()
    if not job_id:
        raise ResolveUpdateError("Could not create Resolve render job.")
    if not project.StartRendering([job_id]):
        raise ResolveUpdateError("Could not start Resolve render job.")


def current_timeline_composition(clip_name: str | None = None):
    project = current_project()
    timeline = project.GetCurrentTimeline()
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
