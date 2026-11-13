import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from resolve_digest.fusion import (PHOTO_BRANCHES, photo_vertical_limits,
                                   fit_photo_text_pair, reflow_composition, update_composition, ResolveUpdateError)
from test_text_layout import layout_comp
from test_fusion import Node, articles


def photo_comp(title_top=2100, title_height=300, body_height=700):
    comp = layout_comp()
    for index in range(1, 6):
        for kind in ('title', 'body'):
            node = comp.nodes[f'{kind}_{index:02d}']
            base_size = node.values['Size']
            base_y = node.values['Center'][2]
            base_top = title_top if kind == 'title' else 1000
            base_height = title_height if kind == 'title' else body_height
            def bounds(frame, *args, node=node, base_size=base_size, base_y=base_y,
                       base_top=base_top, base_height=base_height):
                if comp.locked:
                    raise AssertionError('Measured while locked')
                top = base_top + (node.values['Center'][2] - base_y) * 2160
                h = base_height * node.values['Size'] / base_size
                node.Output.DataWindow = {2: top-h}
                return [2112, top-h, 3600, top]
            node.Output.GetDoD = bounds
            node.Output.Height = 2160
        static, animation, merge = PHOTO_BRANCHES[index-1]
        for name in (static, animation, merge):
            comp.nodes[name] = Node()
        comp.nodes[static].Output = SimpleNamespace(
            GetValue=lambda *args: SimpleNamespace(Height=2160),
            GetDoD=lambda *args: [0,400,1800,1900])
        title, body = comp.nodes[f'title_{index:02d}'], comp.nodes[f'body_{index:02d}']
        def install(expression, title=title, body=body, index=index):
            x, y = eval(expression, {'Point': lambda x,y:(x,y), f'title_{index:02d}':title, f'body_{index:02d}':body})
            body.values['Center'] = {1:x, 2:y}
        body.Center.SetExpression.side_effect=install
    return comp


class PhotoLayoutTests(unittest.TestCase):
    def test_import_preserves_title_layout_and_all_font_sizes(self):
        comp = photo_comp()
        before = []
        for i in range(1, 6):
            title, body = comp.nodes[f'title_{i:02d}'], comp.nodes[f'body_{i:02d}']
            title.values.update(Font='Template font', LayoutWidth=.2, Size=.05)
            before.append((dict(title.values), body.values['Size']))
        update_composition(comp, articles(), body_gap_pixels=100, constrain_to_photo=True)
        for i in range(1, 6):
            title, body = comp.nodes[f'title_{i:02d}'], comp.nodes[f'body_{i:02d}']
            self.assertEqual({k: v for k, v in title.values.items() if k != 'StyledText'}, before[i-1][0])
            self.assertEqual(body.values['Size'], before[i-1][1])
            title.Center.SetExpression.assert_not_called()

    def test_repeated_reflow_keeps_positions_and_sizes_stable(self):
        comp = photo_comp()
        reflow_composition(comp, 100)
        before = {name: dict(node.values) for name, node in comp.nodes.items()}
        reflow_composition(comp, 100)
        for name, node in comp.nodes.items():
            self.assertEqual(node.values, before[name], name)

    def test_keeps_fixed_title_above_photo_top_and_moves_only_body(self):
        comp = photo_comp()
        title, body = comp.nodes['title_01'], comp.nodes['body_01']
        original_title = dict(title.values)
        original_body_size = body.values['Size']
        _, expression = fit_photo_text_pair(comp, title, body, 1, 100)
        title.Output.DataWindow = {2: title.Output.GetDoD(14)[1]}
        _, y = eval(expression, {'Point':lambda x,y:(x,y), 'title_01':title, 'body_01':body})
        body_top = 1000 + (y-.335)*2160
        self.assertEqual(title.values, original_title)
        self.assertEqual(body.values['Size'], original_body_size)
        self.assertEqual(title.Output.GetDoD(14)[3], 2100)
        self.assertGreaterEqual(body_top-700, 400)
        self.assertAlmostEqual(title.Output.DataWindow[2]-body_top, 100, places=6)

    def test_overflow_does_not_shrink_fonts_or_move_title(self):
        comp = photo_comp(body_height=1200)
        title, body = comp.nodes['title_01'], comp.nodes['body_01']
        original_title, original_body = dict(title.values), dict(body.values)
        with self.assertRaisesRegex(ResolveUpdateError, 'не помещается'):
            fit_photo_text_pair(comp, title, body, 1, 300)
        self.assertEqual(title.values, original_title)
        self.assertEqual(body.values, original_body)
        body.Center.SetExpression.assert_not_called()

    def test_different_native_photo_resolution_is_translated_not_scaled(self):
        comp = photo_comp()
        static = comp.nodes[PHOTO_BRANCHES[0][0]]
        static.Output.GetValue=lambda *args:SimpleNamespace(Height=1000)
        static.Output.GetDoD=lambda *args:[0,100,500,900]
        self.assertEqual(photo_vertical_limits(comp,1,2160),(680,1480))

    def test_gap_larger_than_photo_is_an_error(self):
        comp=photo_comp()
        with self.assertRaisesRegex(ResolveUpdateError,'не помещается'):
            fit_photo_text_pair(comp,comp.nodes['title_01'],comp.nodes['body_01'],1,1600)

    def test_unsupported_photo_transform_is_not_silently_ignored(self):
        comp=photo_comp()
        comp.nodes[PHOTO_BRANCHES[0][2]].values['Size']=2
        with self.assertRaises(ResolveUpdateError):
            photo_vertical_limits(comp,1,2160)

    def test_layout_only_keeps_text_and_media_and_groups_undo(self):
        comp=photo_comp()
        for i in range(1,6):
            comp.nodes[f'title_{i:02d}'].values['StyledText']='Title'
            comp.nodes[f'body_{i:02d}'].values['StyledText']='Body'
            comp.nodes[f'image_{i:02d}'].values['Clip']='unchanged.jpg'
        comp.StartUndo,comp.EndUndo=MagicMock(),MagicMock()
        original_titles = [dict(comp.nodes[f'title_{i:02d}'].values) for i in range(1,6)]
        original_sizes = [comp.nodes[f'body_{i:02d}'].values['Size'] for i in range(1,6)]
        reflow_composition(comp,100)
        comp.EndUndo.assert_called_once_with(True)
        for i in range(1,6):
            self.assertEqual(comp.nodes[f'title_{i:02d}'].values['StyledText'],'Title')
            self.assertEqual(comp.nodes[f'image_{i:02d}'].values['Clip'],'unchanged.jpg')
            self.assertEqual(comp.nodes[f'title_{i:02d}'].values, original_titles[i-1])
            self.assertEqual(comp.nodes[f'body_{i:02d}'].values['Size'], original_sizes[i-1])
            comp.nodes[f'body_{i:02d}'].Center.SetExpression.assert_called_once()
