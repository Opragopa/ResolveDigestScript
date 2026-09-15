"""Narrow adapter around Resolve's scripting API; easy to test without Resolve."""
from __future__ import annotations

import os
import math
import re
import sys
from pathlib import Path

from .models import DownloadedArticle


class ResolveUpdateError(RuntimeError):
    pass


# A non-breaking space is supported by Text+ and is more reliable there than a
# manual newline: Fusion may reflow text after a frame or font change.
_RUSSIAN_PREPOSITION = re.compile(
    r"(?iu)(?<![\w\u00A0])"
    r"(в|во|к|ко|с|со|у|о|об|обо|от|до|на|за|по|из|изо|"
    r"для|без|над|под|перед|при|про|через|между)"
    r"[ \t]+(?=\S)"
)


def prevent_hanging_russian_prepositions(text: str) -> str:
    """Keep a Russian preposition with the following word during Text+ reflow."""
    return _RUSSIAN_PREPOSITION.sub(lambda match: f"{match.group(1)}\u00a0", text)


def _input_value(tool, name: str):
    """Read a Fusion input while keeping the adapter usable in unit tests."""
    getter = getattr(tool, "GetInput", None)
    if not callable(getter):
        return None
    try:
        return getter(name)
    except TypeError:
        return getter(name, 0)


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _composition_size(comp) -> tuple[float, float]:
    """Return frame dimensions, with HD as a conservative API-free fallback."""
    prefs = getattr(comp, "GetPrefs", None)
    if callable(prefs):
        try:
            values = prefs() or {}
        except TypeError:
            values = {}
        width = _number(values.get("Comp.FrameFormat.Width"))
        height = _number(values.get("Comp.FrameFormat.Height"))
        if width and height:
            return width, height
    return 1920.0, 1080.0


def _base_text_size(tool) -> float | None:
    """Persist the template size so repeated runs never progressively shrink it."""
    current = _number(_input_value(tool, "Size"))
    if current is None:
        return None
    get_data = getattr(tool, "GetData", None)
    set_data = getattr(tool, "SetData", None)
    key = "ResolveDigest.AutoScaleBaseSize"
    stored = _number(get_data(key)) if callable(get_data) else None
    if stored and stored > 0:
        return stored
    if callable(set_data):
        set_data(key, current)
    return current


def auto_scale_text(tool, comp, text: str) -> float | None:
    """Fit text approximately into this Text+'s existing frame.

    Text+ exposes its frame as normalized Width/Height and font Size. Resolve
    has no scripting API for glyph measurement, so a conservative estimate
    uses average Cyrillic glyph width and line height. It only reduces Size.
    """
    box_width = _number(_input_value(tool, "Width"))
    box_height = _number(_input_value(tool, "Height"))
    base_size = _base_text_size(tool)
    if not box_width or not box_height or not base_size or box_width <= 0 or box_height <= 0:
        return None

    frame_width, frame_height = _composition_size(comp)
    available_width = box_width * frame_width
    available_height = box_height * frame_height
    glyphs = max(len(text.replace("\n", "")), 1)
    font_pixels = base_size * frame_height
    estimated_line_width = max(available_width / (font_pixels * 0.53), 1)
    explicit_lines = max(text.count("\n") + 1, 1)
    estimated_lines = max(math.ceil(glyphs / estimated_line_width), explicit_lines)
    needed_height = estimated_lines * font_pixels * 1.22
    scale = min(1.0, available_height / needed_height)
    size = base_size * scale
    tool.SetInput("Size", size)
    return size


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
            title = _find_required(comp, f"title_{suffix}")
            body = _find_required(comp, f"body_{suffix}")
            title_text = prevent_hanging_russian_prepositions(item.article.title.upper())
            body_text = prevent_hanging_russian_prepositions(item.article.body)
            title.SetInput("StyledText", title_text)
            body.SetInput("StyledText", body_text)
            auto_scale_text(title, comp, title_text)
            auto_scale_text(body, comp, body_text)
            image = _find_required(comp, f"image_{suffix}")
            image.SetInput("Clip", str(Path(item.image_path).resolve()))
            # A still image must remain a still in Fusion.  Without explicit
            # trim bounds Resolve may treat the Loader input as a sequence.
            frame = index - 1
            image.SetInput("ClipTimeStart", frame)
            image.SetInput("ClipTimeEnd", frame)
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
