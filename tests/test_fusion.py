import unittest
from pathlib import Path

from resolve_digest.fusion import ResolveUpdateError, update_composition
from resolve_digest.models import Article, DownloadedArticle


class Node:
    def __init__(self):
        self.values = {}

    def SetInput(self, key, value):
        self.values[key] = value


class Composition:
    def __init__(self, missing=None):
        self.nodes = {f"{kind}_{index:02d}": Node() for kind in ("title", "body", "image") for index in range(1, 7)}
        self.nodes.pop(missing, None)
        self.locked = False

    def Lock(self):
        self.locked = True

    def Unlock(self):
        self.locked = False

    def FindTool(self, name):
        return self.nodes.get(name)


def articles():
    return [DownloadedArticle(Article(f"Title {i}", f"Body {i}", "https://example.test", 1), Path(f"/tmp/news_{i:02d}.jpg"), "") for i in range(1, 7)]


class FusionTests(unittest.TestCase):
    def test_updates_only_reserved_inputs(self):
        comp = Composition()
        update_composition(comp, articles())
        self.assertEqual(comp.nodes["title_01"].values["StyledText"], "Title 1")
        self.assertEqual(comp.nodes["body_06"].values["StyledText"], "Body 6")
        self.assertTrue(comp.nodes["image_02"].values["Clip"].endswith("news_02.jpg"))
        self.assertFalse(comp.locked)

    def test_unlocks_when_template_is_invalid(self):
        comp = Composition("image_03")
        with self.assertRaises(ResolveUpdateError):
            update_composition(comp, articles())
        self.assertFalse(comp.locked)
