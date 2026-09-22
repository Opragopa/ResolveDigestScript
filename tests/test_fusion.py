import unittest
from pathlib import Path

from resolve_digest.fusion import (
    ResolveUpdateError,
    _load_render_preset,
    auto_scale_text,
    prevent_hanging_russian_prepositions,
    update_composition,
)
from resolve_digest.models import Article, DownloadedArticle


class Node:
    def __init__(self):
        self.values = {}

    def SetInput(self, key, value):
        self.values[key] = value

    def GetInput(self, key):
        return self.values.get(key)

    def GetData(self, key):
        return getattr(self, "data", {}).get(key)

    def SetData(self, key, value):
        if not hasattr(self, "data"):
            self.data = {}
        self.data[key] = value


class Composition:
    def __init__(self, missing=None):
        self.nodes = {f"{kind}_{index:02d}": Node() for kind in ("title", "body", "image") for index in range(1, 6)}
        self.nodes.pop(missing, None)
        self.locked = False

    def GetPrefs(self):
        return {"Comp.FrameFormat.Width": 1920, "Comp.FrameFormat.Height": 1080}

    def Lock(self):
        self.locked = True

    def Unlock(self):
        self.locked = False

    def FindTool(self, name):
        return self.nodes.get(name)


def articles():
    return [DownloadedArticle(Article(f"Title {i}", f"Body {i}", "https://example.test", i), Path(f"/tmp/news_{i:02d}/photo_01.jpg"), "", 5) for i in range(1, 6)]


class FusionTests(unittest.TestCase):
    def test_updates_only_reserved_inputs(self):
        comp = Composition()
        update_composition(comp, articles())
        self.assertEqual(comp.nodes["title_01"].values["StyledText"], "TITLE 1")
        self.assertEqual(comp.nodes["body_05"].values["StyledText"], "Body 5")
        self.assertTrue(comp.nodes["image_02"].values["Clip"].endswith("news_02/photo_01.jpg"))
        self.assertEqual(comp.nodes["image_02"].values["ClipTimeStart"], 1)
        self.assertEqual(comp.nodes["image_02"].values["ClipTimeEnd"], 1)
        self.assertFalse(comp.locked)

    def test_prevents_hanging_russian_prepositions(self):
        self.assertEqual(
            prevent_hanging_russian_prepositions("В городе и на реке, через неделю."),
            "В\u00a0городе и на\u00a0реке, через\u00a0неделю.",
        )

    def test_scales_from_text_box_and_keeps_template_size(self):
        comp = Composition()
        node = comp.nodes["body_01"]
        node.values.update({"Width": 0.2, "Height": 0.4, "Size": 0.1})
        first = auto_scale_text(node, comp, "длинный текст " * 50)
        second = auto_scale_text(node, comp, "короткий текст")
        self.assertLess(first, 0.1)
        self.assertEqual(second, 0.1)

    def test_each_image_uses_matching_news_slot(self):
        comp = Composition()
        update_composition(comp, articles())
        for index in range(1, 6):
            self.assertTrue(comp.nodes[f"image_{index:02d}"].values["Clip"].endswith(f"news_{index:02d}/photo_01.jpg"))
            self.assertEqual(comp.nodes[f"image_{index:02d}"].values["ClipTimeStart"], index - 1)
            self.assertEqual(comp.nodes[f"image_{index:02d}"].values["ClipTimeEnd"], index - 1)

    def test_unlocks_when_template_is_invalid(self):
        comp = Composition("image_03")
        with self.assertRaises(ResolveUpdateError):
            update_composition(comp, articles())
        self.assertFalse(comp.locked)

    def test_loads_preset_by_case_insensitive_name(self):
        class Project:
            def GetRenderPresetList(self):
                return ["Дайджест на экраны"]

            def LoadRenderPreset(self, name):
                return name == "Дайджест на экраны"

        self.assertEqual(_load_render_preset(Project(), "дайджест на экраны"), "Дайджест на экраны")
