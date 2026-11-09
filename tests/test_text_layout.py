import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from resolve_digest.fusion import body_layout_plan, auto_scale_text, update_composition, ResolveUpdateError
from test_fusion import Composition, articles


def layout_comp():
    comp = Composition()
    for index in range(1, 6):
        for kind in ('title', 'body'):
            node = comp.nodes[f'{kind}_{index:02d}']
            node.values.update(Width=3840, Height=2160, LayoutWidth=.4,
                               LayoutHeight=.3 if kind == 'title' else .4,
                               LayoutType=1, Size=.0378 if kind == 'title' else .0191,
                               Center={1: .75, 2: .615 if kind == 'title' else .335})
            node.Center = SimpleNamespace(SetExpression=MagicMock())
            rect = [2112, 1200, 3600, 1600] if kind == 'title' else [2112, 400, 3600, 1000]
            def bounds(frame, flags, proxy, rect=rect):
                if comp.locked:
                    raise AssertionError('DoD must not be evaluated while locked')
                if frame != 14 or proxy != 0:
                    raise AssertionError('Wrong sample frame or proxy')
                return {i + 1: v for i, v in enumerate(rect)}
            node.Output = SimpleNamespace(GetDoD=bounds)
    return comp


class TextLayoutTests(unittest.TestCase):
    def test_reads_layout_dimensions_instead_of_4k_image_dimensions(self):
        comp = layout_comp()
        node = comp.nodes['body_01']
        size = auto_scale_text(node, comp, 'Длинное описание ' * 250)
        self.assertLess(size, .0191)
        node.values['LayoutHeight'] = .02
        smaller = auto_scale_text(node, comp, 'Длинное описание ' * 250)
        self.assertLess(smaller, size)

    def test_measures_body_top_and_title_bottom_with_20_pixel_gap(self):
        comp = layout_comp()
        title, body = comp.nodes['title_01'], comp.nodes['body_01']
        center, expr = body_layout_plan(title, body, comp, 'title_01', 20)
        self.assertIs(center, body.Center)
        # Evaluate the generated expression independently using Fusion's shape.
        title.Output.DataWindow = {2: 1200}
        title.Output.Height = 2160
        x, y = eval(expr, {'Point': lambda x, y: (x, y), 'title_01': title, 'body_01': body})
        new_body_top = 1000 + (y - .335) * 2160
        self.assertAlmostEqual(1200 - new_body_top, 20, places=7)
        self.assertEqual(x, .75)
        self.assertNotIn('body_01.Output', expr)
        # Manual changes to title height/position follow without rerunning.
        title.Output.DataWindow[2] = 1100
        _, y2 = eval(expr, {'Point': lambda x, y: (x, y), 'title_01': title, 'body_01': body})
        self.assertAlmostEqual((y - y2) * 2160, 100)

    def test_all_five_expressions_are_installed_in_same_undo_group(self):
        comp = layout_comp()
        comp.StartUndo, comp.EndUndo = MagicMock(), MagicMock()
        update_composition(comp, articles(), body_gap_pixels=20)
        for index in range(1, 6):
            setter = comp.nodes[f'body_{index:02d}'].Center.SetExpression
            setter.assert_called_once()
            self.assertIn(f'title_{index:02d}.Output', setter.call_args.args[0])
        self.assertFalse(comp.locked)
        comp.EndUndo.assert_called_once_with(True)

    def test_gap_changes_live_and_can_compensate_for_text_box_padding(self):
        comp = layout_comp()
        title, body = comp.nodes['title_01'], comp.nodes['body_01']
        body.UserControls = {'Existing': {'LINKS_Name': 'Keep me'}}
        _, expr = body_layout_plan(title, body, comp, 'title_01', 80)
        title.Output.DataWindow = {2: 1200}
        title.Output.Height = 2160
        context = {'Point': lambda x, y: (x, y), 'title_01': title, 'body_01': body}
        _, original_y = eval(expr, context)
        body.SetInput('DigestGap', -120)
        _, adjusted_y = eval(expr, context)
        self.assertAlmostEqual((adjusted_y - original_y) * 2160, 200)
        self.assertIn('Existing', body.UserControls)
        self.assertLess(body.UserControls['DigestGap']['INP_MinAllowed'], 0)
        self.assertNotIn('body_01.Output', expr)

    def test_gap_controls_are_independent_for_each_news(self):
        comp = layout_comp()
        update_composition(comp, articles(), body_gap_pixels=80)
        comp.nodes['body_01'].SetInput('DigestGap', 15)
        self.assertEqual(comp.nodes['body_02'].GetInput('DigestGap'), 80)

    def test_empty_bounds_fail_without_installing_any_expression(self):
        comp = layout_comp()
        comp.nodes['body_05'].Output.GetDoD = lambda *args: [0, 0, 0, 0]
        with self.assertRaisesRegex(ResolveUpdateError, 'Пустые'):
            update_composition(comp, articles(), body_gap_pixels=20)
        self.assertFalse(comp.locked)
        for index in range(1, 6):
            comp.nodes[f'body_{index:02d}'].Center.SetExpression.assert_not_called()

    def test_body_must_fit_below_title(self):
        comp = layout_comp()
        with self.assertRaisesRegex(ResolveUpdateError, 'не помещается'):
            body_layout_plan(comp.nodes['title_01'], comp.nodes['body_01'], comp, 'title_01', 800)

    def test_full_frame_bounds_are_rejected(self):
        comp = layout_comp()
        comp.nodes['title_01'].Output.GetDoD = lambda *args: [0, 0, 3840, 2160]
        with self.assertRaisesRegex(ResolveUpdateError, 'всего кадра'):
            body_layout_plan(comp.nodes['title_01'], comp.nodes['body_01'], comp, 'title_01', 20)

    def test_invalid_gap_is_rejected(self):
        comp = layout_comp()
        for gap in (-1, float('nan'), float('inf')):
            with self.subTest(gap=gap), self.assertRaises(ResolveUpdateError):
                body_layout_plan(comp.nodes['title_01'], comp.nodes['body_01'], comp, 'title_01', gap)
