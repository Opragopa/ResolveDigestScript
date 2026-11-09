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


_resolve_instance = None


def set_resolve_instance(instance):
    """Use the object provided by the menu host without importing an API DLL."""
    global _resolve_instance
    _resolve_instance = instance


def _set_input(tool, name, value):
    if tool.SetInput(name, value) is False:
        raise ResolveUpdateError("Fusion отклонил запись входа: " + name)


def validate_composition(comp):
    """Check every slot before the first write or network request."""
    nodes = []
    for index in range(1, 6):
        group = []
        for kind, expected in (("title", "TextPlus"), ("body", "TextPlus"), ("image", "Loader")):
            name = "{}_{:02d}".format(kind, index)
            node = _find_required(comp, name)
            attrs = getattr(node, "GetAttrs", None)
            if callable(attrs):
                actual = (attrs() or {}).get("TOOLS_RegID")
                if actual and actual != expected:
                    raise ResolveUpdateError("Нода {} должна иметь тип {}, получен {}".format(name, expected, actual))
            group.append(node)
        nodes.append(group)
    return nodes


# A non-breaking space is supported by Text+ and is more reliable there than a
# manual newline: Fusion may reflow text after a frame or font change.
_RUSSIAN_PREPOSITION = re.compile(
    r"(?iu)(?<![\w\u00A0])"
    r"(в|во|к|ко|с|со|у|о|об|обо|от|до|на|за|по|из|изо|"
    r"для|без|над|под|перед|при|про|через|между|и|а|но|же|ли|бы|да|ни)"
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
        number = float(value)
        return number if math.isfinite(number) else None
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


def _text_frame_size(tool, comp):
    width = _number(_input_value(tool, "Width"))
    height = _number(_input_value(tool, "Height"))
    if width and height and width > 1 and height > 1:
        return width, height
    return _composition_size(comp)


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

    Text+ exposes its text frame as LayoutWidth/LayoutHeight (Width/Height
    describe the output image). This pre-pass estimates wrapping using average
    Cyrillic glyph width and line height. Positioning later uses actual DoD.
    It only reduces Size.
    """
    box_width = _number(_input_value(tool, "LayoutWidth"))
    box_height = _number(_input_value(tool, "LayoutHeight"))
    # Compatibility with older adapters that exposed normalized box sizes.
    if box_width is None:
        width = _number(_input_value(tool, "Width"))
        box_width = width if width is not None and 0 < width <= 1 else None
    if box_height is None:
        height = _number(_input_value(tool, "Height"))
        box_height = height if height is not None and 0 < height <= 1 else None
    base_size = _base_text_size(tool)
    if not box_width or not box_height or not base_size or box_width <= 0 or box_height <= 0:
        return None

    frame_width, frame_height = _text_frame_size(tool, comp)
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
    _set_input(tool, "Size", size)
    return size


def _components(value, count):
    if isinstance(value, dict):
        if all(index in value for index in range(1, count + 1)):
            values = [value[index] for index in range(1, count + 1)]
        elif all(index in value for index in range(count)):
            values = [value[index] for index in range(count)]
        elif count == 2 and "X" in value and "Y" in value:
            values = [value["X"], value["Y"]]
        elif count == 4:
            for keys in (("left", "bottom", "right", "top"),
                         ("Left", "Bottom", "Right", "Top"),
                         ("x1", "y1", "x2", "y2")):
                if all(key in value for key in keys):
                    values = [value[key] for key in keys]
                    break
            else:
                raise ResolveUpdateError("Fusion вернул неизвестный формат прямоугольника.")
        else:
            raise ResolveUpdateError("Fusion вернул неизвестный формат координат.")
    elif isinstance(value, (list, tuple)) and len(value) >= count:
        values = value[:count]
    elif value is not None:
        # Native bridge wrappers may expose a Point/Rect object rather than a
        # Python table. Accept only complete, finite coordinate sets.
        keys_options = (("X", "Y"),) if count == 2 else (
            ("left", "bottom", "right", "top"),
            ("Left", "Bottom", "Right", "Top"),
            ("x1", "y1", "x2", "y2"), ("X1", "Y1", "X2", "Y2"))
        values = None
        for keys in keys_options:
            candidate = [getattr(value, key, None) for key in keys]
            if all(_number(item) is not None for item in candidate):
                values = candidate
                break
        if values is None:
            raise ResolveUpdateError("Fusion вернул неизвестный объект координат: " + type(value).__name__)
    else:
        raise ResolveUpdateError("Fusion не вернул координаты текста.")
    numbers = [_number(item) for item in values]
    if any(item is None for item in numbers):
        raise ResolveUpdateError("Fusion вернул недопустимые координаты текста.")
    return numbers


def _rendered_image(output, frame):
    getter = getattr(output, "GetValue", None)
    if not callable(getter):
        raise ResolveUpdateError("Fusion не предоставляет Output.GetValue.")
    try:
        image = getter(frame, 0, 0)
    except TypeError:
        image = getter(frame)
    if image is None:
        image = getter(frame)
    return image


def _text_bounds(tool, frame, rendered_image=None, label=None):
    """Read a real rectangle; some Resolve bridges return None from GetDoD.

    Prefer the already-rendered image when available. Otherwise retain the
    cheap DoD path, then render and read Image.DataWindow as a fallback. Never
    invent a full-frame rectangle when the bridge supplies no coordinates.
    """
    output = getattr(tool, "Output", None)
    getter = getattr(output, "GetDoD", None)
    sources = []
    if rendered_image is not None:
        sources.append(("Image.DataWindow", lambda: getattr(rendered_image, "DataWindow", None)))
    if callable(getter):
        sources.extend((("GetDoD(frame,0,0)", lambda: getter(frame, 0, 0)),
                        ("GetDoD(frame)", lambda: getter(frame))))
    if callable(getattr(output, "GetValue", None)):
        sources.append(("GetValue.DataWindow", lambda: getattr(_rendered_image(output, frame), "DataWindow", None)))
    diagnostics = []
    for method, read in sources:
        value = None
        try:
            value = read()
            rect = _components(value, 4)
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                raise ResolveUpdateError("Пустые границы изображения")
            return rect
        except Exception as error:
            diagnostics.append(f"{method}: {type(value).__name__} {repr(value)[:160]}; {type(error).__name__}: {error}")
    if label is None:
        attrs = getattr(tool, "GetAttrs", None)
        label = (attrs() or {}).get("TOOLS_Name") if callable(attrs) else None
    details = " | ".join(diagnostics) or "Нет методов GetDoD/GetValue"
    print(f"Resolve Digest bounds failure: node={label or '?'} frame={frame}; {details}")
    raise ResolveUpdateError(
        f"Не удалось измерить границы ноды {label or 'Text+'} на кадре {frame}. "
        f"Fusion не вернул подходящие координаты. {details}")


def _install_gap_control(body, gap):
    """Expose a signed pixel gap without replacing existing custom controls."""
    controls = dict(getattr(body, "UserControls", None) or {})
    controls["DigestGap"] = {
        "LINKS_Name": "Title / body gap (px)",
        "LINKID_DataType": "Number",
        "INPID_InputControl": "SliderControl",
        "ICS_ControlPage": "Digest",
        "INP_Default": gap,
        "INP_MinScale": -500,
        "INP_MaxScale": 1000,
        "INP_MinAllowed": -100000,
        "INP_MaxAllowed": 100000,
    }
    body.UserControls = controls
    refresh = getattr(body, "Refresh", None)
    if callable(refresh):
        refresh()
    _set_input(body, "DigestGap", gap)


def body_layout_plan(title, body, comp, title_name, gap_pixels, sample_frame=14, photo_limits=None):
    """Measure before setting an expression; never reference body's own output.

    Supplied template: text is static, title/body share downstream transforms,
    and body_01 finishes its alpha fade at frame 14. DoD is queried unlocked.
    """
    gap = _number(gap_pixels)
    if gap is None or gap < 0:
        raise ResolveUpdateError("Отступ title/body должен быть конечным числом от 0 пикселей.")
    for node in (title, body):
        if _number(_input_value(node, "LayoutType")) != 1:
            raise ResolveUpdateError("Для автоматического отступа title и body должны использовать Layout → Frame.")
    center_input = getattr(body, "Center", None)
    if not callable(getattr(center_input, "SetExpression", None)):
        raise ResolveUpdateError("Не удалось получить вход Center у body для привязки к title.")
    try:
        center = body.GetInput("Center", sample_frame)
    except TypeError:
        center = body.GetInput("Center")
    x, y = _components(center, 2)
    title_width, title_height = _text_frame_size(title, comp)
    body_width, body_height = _text_frame_size(body, comp)
    if (title_width, title_height) != (body_width, body_height):
        raise ResolveUpdateError("Разрешение title и body должно совпадать.")
    title_rect = _text_bounds(title, sample_frame)
    body_rect = _text_bounds(body, sample_frame)
    for rect in (title_rect, body_rect):
        if rect[0] <= 0 and rect[1] <= 0 and rect[2] >= body_width and rect[3] >= body_height:
            raise ResolveUpdateError("Text+ вернул границы всего кадра: точный отступ измерить невозможно.")
    top_offset = body_rect[3] / body_height - y
    new_top = title_rect[1] - gap
    new_bottom = new_top - (body_rect[3] - body_rect[1])
    if new_bottom < 0 or new_top > body_height:
        raise ResolveUpdateError("Описание не помещается под заголовком: уменьшите Size или отступ title/body.")
    # A negative gap compensates for transparent padding in Text+'s DoD.
    # Reading a custom input on body is safe; reading body.Output is cyclic.
    _install_gap_control(body, gap)
    body_name = title_name.replace("title_", "body_", 1)
    live_gap = f"{body_name}.DigestGap / {body_height:.12g}"
    expression = (
        f"Point({x:.12g}, {title_name}.Output.DataWindow[2] / "
        f"{title_name}.Output.Height - ({live_gap}) - ({top_offset:.12g}))"
    )
    if photo_limits is not None:
        bottom, top = photo_limits
        lower = (bottom + body_rect[3] - body_rect[1]) / body_height - top_offset
        upper = top / body_height - top_offset
        desired = (f"{title_name}.Output.DataWindow[2] / {title_name}.Output.Height"
                   f" - ({live_gap}) - ({top_offset:.12g})")
        expression = f"Point({x:.12g}, min({upper:.12g}, max({lower:.12g}, {desired})))"
    return center_input, expression


# Static photo transforms and final photo merges in the supplied template.
PHOTO_BRANCHES = (
    ("Transform2", "Transform6_2_2", "Merge2_1_3"),
    ("Transform2_2", "Transform6_2", "Merge2_1_1_2_2"),
    ("Transform2_2_1", "Transform6_2_1", "Merge2_1_1_2_2_1"),
    ("Transform2_2_1_1", "Transform6_2_1_1", "Merge2_1_1_2_2_1_1"),
    ("Transform2_2_1_1_1", "Transform6_2_1_1_1", "Merge2_1_1_2_2_1_1_1"),
)


def _at(tool, name, frame):
    try:
        return tool.GetInput(name, frame)
    except TypeError:
        return tool.GetInput(name)


def photo_vertical_limits(comp, index, canvas_height):
    """Map native photo DoD to the Merge background, pixel for pixel.

    The template's animated transform only slides horizontally. The final
    Merge is centred at size=1; differing foreground/background resolutions
    require a half-height translation, not normalized scaling.
    """
    static_name, animation_name, merge_name = PHOTO_BRANCHES[index - 1]
    static = _find_required(comp, static_name)
    animation = _find_required(comp, animation_name)
    merge = _find_required(comp, merge_name)
    for node in (animation, merge):
        size = _number(_input_value(node, "Size"))
        angle = _number(_input_value(node, "Angle"))
        if (size is not None and abs(size - 1) > 1e-8) or (angle is not None and abs(angle) > 1e-8):
            raise ResolveUpdateError("Дополнительный поворот/масштаб фото требует настройки границ шаблона.")
        for frame in (0, 14, 750, 1499):
            center = _at(node, "Center", frame)
            if center is not None and abs(_components(center, 2)[1] - .5) > 1e-8:
                raise ResolveUpdateError("Вертикальное смещение фото в анимации/Merge не поддерживается этим шаблоном.")
    output = getattr(static, "Output", None)
    if not callable(getattr(output, "GetValue", None)):
        raise ResolveUpdateError("Не удалось получить разрешение обработанной фотографии.")
    image = _rendered_image(output, 0)
    native_height = _number(getattr(image, "Height", None))
    if native_height is None or native_height <= 0:
        raise ResolveUpdateError("Фотография не загружена на кадре 0: " + static_name)
    rect = _text_bounds(static, 0, rendered_image=image, label=static_name)
    shift = (canvas_height - native_height) / 2
    bottom, top = max(0., rect[1] + shift), min(canvas_height, rect[3] + shift)
    if top <= bottom:
        raise ResolveUpdateError("Фотография находится за пределами кадра: " + static_name)
    return bottom, top


def fit_photo_text_pair(comp, title, body, index, gap):
    """Fit both texts and requested gap within actual visible photo height."""
    _, height = _text_frame_size(title, comp)
    bottom, top = photo_vertical_limits(comp, index, height)
    available = top - bottom
    if gap >= available - 2:
        raise ResolveUpdateError(f"Отступ {gap:g} px не помещается в высоту фото {available:g} px (новость {index}).")
    for _ in range(16):
        tr, br = _text_bounds(title, 14), _text_bounds(body, 14)
        th, bh = tr[3] - tr[1], br[3] - br[1]
        total = th + gap + bh
        if total <= available - 2:
            break
        # Leave room for body even when the title alone is too tall.
        node = title if th >= (available - gap) * .65 else body
        current = _number(_input_value(node, "Size"))
        room = (available - gap) * .55 if node is title else available - gap - th - 2
        measured = th if node is title else bh
        if current is None or room <= 0:
            raise ResolveUpdateError("Не удалось подобрать размер текста в границах фото.")
        size = max(.004, current * min(.9, .95 * room / measured))
        if size >= current:
            raise ResolveUpdateError(f"Текст новости {index} не помещается даже при минимальном Size. Уменьшите отступ.")
        _set_input(node, "Size", size)
    else:
        raise ResolveUpdateError(f"Не удалось вписать текст новости {index} в высоту фотографии.")
    # Preserve the title position where possible; move the whole block only
    # as far as needed to stay inside the photograph.
    x, y = _components(_at(title, "Center", 14), 2)
    new_top = min(top - 1, max(tr[3], bottom + 1 + total))
    if abs(new_top - tr[3]) > 1e-8:
        _set_input(title, "Center", {1: x, 2: y + (new_top - tr[3]) / height})
    return body_layout_plan(title, body, comp, f"title_{index:02d}", gap,
                            photo_limits=(bottom, top))


def _layout_plans(comp, nodes, gap, constrain_to_photo):
    return [fit_photo_text_pair(comp, title, body, index, gap) if constrain_to_photo
            else body_layout_plan(title, body, comp, f"title_{index:02d}", gap)
            for index, (title, body, _) in enumerate(nodes, start=1)]


def _verify_photo_layout(comp, nodes, gap):
    for index, (title, body, _) in enumerate(nodes, start=1):
        _, height = _text_frame_size(title, comp)
        bottom, top = photo_vertical_limits(comp, index, height)
        tr, br = _text_bounds(title, 14), _text_bounds(body, 14)
        if tr[3] > top + 1 or br[1] < bottom - 1 or abs(tr[1] - br[3] - gap) > 2:
            raise ResolveUpdateError(
                f"Fusion не подтвердил отступ/границы текста в новости {index}. "
                "Проверьте выражения Center и отмените группу верстки через Undo.")


def reflow_composition(comp, gap_pixels=80.):
    gap = _number(gap_pixels)
    if gap is None or gap < 0:
        raise ResolveUpdateError("Отступ должен быть конечным числом от 0 пикселей.")
    nodes = validate_composition(comp)
    started = False
    try:
        if callable(getattr(comp, "StartUndo", None)) and callable(getattr(comp, "EndUndo", None)):
            comp.StartUndo("Resolve Digest — верстка")
            started = True
        for title, body, _ in nodes:
            for node in (title, body):
                auto_scale_text(node, comp, str(_input_value(node, "StyledText") or ""))
        plans = _layout_plans(comp, nodes, gap, True)
        for center, expression in plans:
            if center.SetExpression(expression) is False:
                raise ResolveUpdateError("Fusion отклонил выражение отступа body.")
        _verify_photo_layout(comp, nodes, gap)
    finally:
        if started:
            comp.EndUndo(True)


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


def update_composition(comp, articles: list[DownloadedArticle], body_gap_pixels=None,
                       constrain_to_photo=False) -> None:
    """Replace five reserved node groups, leaving the Fusion graph untouched."""
    if len(articles) != 5:
        raise ResolveUpdateError("Для обновления требуется ровно пять новостей.")
    if body_gap_pixels is not None:
        gap = _number(body_gap_pixels)
        if gap is None or gap < 0:
            raise ResolveUpdateError("Отступ title/body должен быть конечным числом от 0 пикселей.")
    nodes = validate_composition(comp)
    for item in articles:
        if not 1 <= item.article.photo_number <= item.image_count:
            raise ResolveUpdateError("Недопустимый номер фотографии: " + str(item.article.photo_number))
    undo_open = False
    locked = False
    try:
        if (callable(getattr(comp, "StartUndo", None))
                and callable(getattr(comp, "EndUndo", None))):
            comp.StartUndo("Resolve Digest")
            undo_open = True
        comp.Lock()
        locked = True
        for index, item in enumerate(articles, start=1):
            # Keep each article's title/body/photo bound to the same numeric
            # slot.  Uppercase is intentional for the on-screen title style.
            title, body, image = nodes[index - 1]
            title_text = prevent_hanging_russian_prepositions(item.article.title.upper())
            body_text = prevent_hanging_russian_prepositions(item.article.body)
            _set_input(title, "StyledText", title_text)
            _set_input(body, "StyledText", body_text)
            auto_scale_text(title, comp, title_text)
            auto_scale_text(body, comp, body_text)
            # Keep every downloaded photo available as a Loader sequence.
            # Trim selects the requested frame but remains editable in Fusion.
            _set_input(image, "Clip", str(Path(item.image_path).resolve()))
            frame = item.article.photo_number - 1
            _set_input(image, "ClipTimeStart", frame)
            _set_input(image, "ClipTimeEnd", frame)
        if body_gap_pixels is not None:
            # Evaluating outputs while locked can return stale bounds or block
            # rendering. Keep one undo group, but measure after unlocking.
            comp.Unlock()
            locked = False
            plans = _layout_plans(comp, nodes, gap, constrain_to_photo)
            comp.Lock()
            locked = True
            for center_input, expression in plans:
                if center_input.SetExpression(expression) is False:
                    raise ResolveUpdateError("Fusion отклонил выражение автоматического отступа body.")
            if constrain_to_photo:
                comp.Unlock()
                locked = False
                _verify_photo_layout(comp, nodes, gap)
    finally:
        try:
            if locked:
                comp.Unlock()
        finally:
            if undo_open:
                # Keep even a partial failed edit in a group for manual Undo.
                comp.EndUndo(True)


def current_project():
    resolve = _resolve_instance
    if resolve is None:
        resolve = _resolve_api().scriptapp("Resolve")
    manager = resolve.GetProjectManager() if resolve is not None else None
    project = manager.GetCurrentProject() if manager is not None else None
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
