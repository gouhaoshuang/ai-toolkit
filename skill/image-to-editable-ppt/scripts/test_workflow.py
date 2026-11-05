"""验证真实产物中的可编辑性、分组坐标、图表数据与安全预览行为。"""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, skipUnless
from zipfile import ZipFile
import shutil
import os

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.oxml.ns import qn

from editable_ppt import Deck, walk_shapes
from pptx_tool import audit, inventory, render


def fixture(root):
    # 自造图像只用于验证真实局部裁切，不提交用户素材或生成文件。
    source = root / '示意原图.png'
    im = Image.new('RGB', (400, 300), '#ffffff')
    draw = ImageDraw.Draw(im); draw.ellipse((40, 40, 110, 110), fill='#38b4c0')
    im.save(source)
    deck = Deck(1000, 750, font='Noto Sans CJK SC')
    first = deck.slide()
    deck.text(35, 25, 920, 55, '图像重建验证：文字、公式与可编辑数据', size=30, bold=True, color='12345A')
    with deck.group('流程') as group:
        deck.gradient(deck.box(40, 100, 270, 150, 'EEF7FF', 'B8CFE8', 12), 'F4FAFF', 'DFEDFC')
        deck.text(60, 125, 220, 60, '学生生成轨迹\n教师指导分布', size=22)
        with deck.group('嵌套节点'):
            deck.box(360, 100, 280, 150, 'FFF1F0', 'E8B7B4', 12)
            deck.text(380, 130, 235, 50, [
                {'text': 'p', 'font': 'Times New Roman', 'italic': True},
                {'text': 'T', 'font': 'Times New Roman', 'size': 15, 'baseline': -23000},
                {'text': ' 与 p', 'font': 'Times New Roman'},
                {'text': 'S', 'font': 'Times New Roman', 'size': 15, 'baseline': -23000},
            ], size=25)
        deck.route([(310, 175), (360, 175)], color='346FAD', width=2)
    # 非单位 group 映射：防止辅助函数仅在 chOff==off 时碰巧通过。
    group.width = round(group.width * .85)
    deck.bezier((650, 240), (750, 270), (730, 110), (650, 140), color='D34150', width=2)
    deck.crop_image(source, box=(40, 40, 110, 110), dest=(810, 105, 80, 80))
    table = deck.shapes.add_table(2, 2, deck.u(40), deck.u(290), deck.u(350), deck.u(100)).table
    for i, row in enumerate([['类别', '概率'], ['教师', '26.150']]):
        for j, text in enumerate(row):
            table.cell(i, j).text = text
    deck.bar_chart(420, 285, 520, 320, ['教师', '学生', '基线'], [26.150, 14.835, 48.036],
                   ['00938A', 'D99A38', '4477AA'], maximum=60, major=15,
                   number_format='0.000', size=18)
    second = deck.slide()
    deck.text(40, 40, 900, 60, '第二页：保留 4:3 比例', size=32, color='12345A', bold=True)
    deck.box(40, 160, 920, 450, 'F4F9FF', 'BCD8F5', 12)
    deck.text(80, 210, 800, 90, '无需生成式图像服务\n先逐项拆解，再核验预览', size=27)
    return deck, first, second


def leaf_geometry(shapes, sx=1., sy=1., tx=0., ty=0.):
    """把任意组坐标映射到页面，用于核验缩放后的真实可见位置。"""
    result = []
    for shape in shapes:
        left, top = tx + sx*shape.left, ty + sy*shape.top
        w, h = sx*shape.width, sy*shape.height
        if shape.shape_type == 6:
            xf = shape._element.find('p:grpSpPr/a:xfrm', shape._element.nsmap)
            off, ext = xf.find(qn('a:chOff')), xf.find(qn('a:chExt'))
            gx, gy = w/int(ext.get('cx')), h/int(ext.get('cy'))
            result += leaf_geometry(shape.shapes, gx, gy,
                                    left-gx*int(off.get('x')), top-gy*int(off.get('y')))
        else:
            result.append((left, top, w, h))
    return result


class WorkflowTest(TestCase):
    def test_roundtrip_inset_crop_chart_and_table(self):
        with TemporaryDirectory(prefix='ppt-skill-check-') as temp:
            root = Path(temp); deck, slide, _ = fixture(root)
            before = root / 'before.pptx'; deck.save(before)
            top_geometry = [(s.left, s.top, s.width, s.height) for s in slide.shapes]
            old_leaf_geometry = leaf_geometry(slide.shapes)
            table = next(s.table for s in walk_shapes(slide.shapes) if s.has_table)
            old_widths = [c.width for c in table.columns]
            old_heights = [r.height for r in table.rows]
            before_font = next(slide._element.iter(qn('a:rPr'))).get('sz')
            deck.inset(slide, .9)
            deck.inset(deck.prs.slides[1], .9)
            output = root / '成品 & 测试.pptx'; deck.save(output)
            report = audit(output)
            self.assertEqual(report['pages'], 2)
            self.assertEqual(report['shape_xml_order_errors'], [])
            self.assertTrue(all(not page['out_of_bounds'] for page in report['slides']))
            self.assertEqual(report['slides'][0]['sub_or_superscript_runs'], 2)
            self.assertEqual(report['slides'][0]['tables'][0], [['类别', '概率'], ['教师', '26.150']])
            plot = report['slides'][0]['charts'][0]['plots'][0]
            self.assertEqual(plot['categories'], ['教师', '学生', '基线'])
            self.assertEqual(plot['series'][0]['values'], [26.15, 14.835, 48.036])
            self.assertEqual(plot['data_label_format'], '0.000')
            self.assertEqual(len(report['embedded_objects']), 1)
            self.assertEqual(report['slides'][0]['images'][0]['embedded_pixels'], [70, 70])
            self.assertEqual(report['slides'][0]['images'][0]['crop'], [0, 0, 0, 0])
            # 在保存后的 XML 中核对缩放，不依赖生成时的临时变量。
            reread = Presentation(output); first = reread.slides[0]
            dx, dy = .05 * reread.slide_width, .05 * reread.slide_height
            for old, shape in zip(top_geometry, first.shapes):
                for actual, expected in zip((shape.left, shape.top, shape.width, shape.height),
                                            (.9*old[0]+dx, .9*old[1]+dy, .9*old[2], .9*old[3])):
                    self.assertLessEqual(abs(actual - expected), 2)
            for old, actual in zip(old_leaf_geometry, leaf_geometry(first.shapes)):
                expected = [.9*old[0]+dx, .9*old[1]+dy, .9*old[2], .9*old[3]]
                for a, e in zip(actual, expected):
                    self.assertLessEqual(abs(a-e), 3)
            table = next(s.table for s in walk_shapes(first.shapes) if s.has_table)
            self.assertEqual([c.width for c in table.columns], [round(.9*w) for w in old_widths])
            self.assertEqual([r.height for r in table.rows], [round(.9*h) for h in old_heights])
            self.assertEqual(int(next(first._element.iter(qn('a:rPr'))).get('sz')), round(.9*int(before_font)))
            with ZipFile(before) as z1, ZipFile(output) as z2:
                for n in report['embedded_objects']:
                    self.assertEqual(z1.read(n), z2.read(n))
            # 同时检查数学下标和剪裁后的图像像素仍能读回。
            pic = next(s for s in walk_shapes(first.shapes) if s.shape_type == 13)
            self.assertEqual(Image.open(BytesIO(pic.image.blob)).size, (70, 70))

    def test_input_validation_and_natural_sort(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for n in ['10.png', '2.png', '1.png']:
                Image.new('RGB', (30, 20)).save(root/n)
            self.assertEqual([Path(p['path']).name for p in inventory(root)], ['1.png', '2.png', '10.png'])
            deck = Deck(1000, 750); s = deck.slide()
            with self.assertRaises(ValueError): deck.inset(s, 0)
            with self.assertRaises(ValueError): deck.crop_image(root/'1.png', (-1, 0, 10, 10), (0, 0, 10, 10))
            with self.assertRaises(ValueError):
                deck.bar_chart(0, 0, 10, 10, ['x'], [float('nan')], ['FFFFFF'], 1, .1)

    @skipUnless(shutil.which('libreoffice') and shutil.which('pdftoppm'), '需要 LibreOffice 与 Poppler')
    def test_real_render_and_stale_output_protection(self):
        # 设置目录可留存本次实际生成的预览供人工查看，默认仅用临时目录。
        with TemporaryDirectory(prefix='ppt-skill-render-') as temp:
            root = Path(os.environ.get('PPT_SKILL_TEST_ARTIFACTS', temp))
            root.mkdir(parents=True, exist_ok=True)
            deck, first, second = fixture(root)
            deck.inset(first); deck.inset(second)
            source = deck.save(root/'合成样例.pptx')
            out = root/'preview'; result = render(source, out, scale_to=1000, overwrite=True)
            self.assertEqual(len(result['pages']), 2)
            self.assertFalse(result['visual_review_performed'])
            with self.assertRaises(FileExistsError): render(source, out)
            unrelated = out/'用户文件.txt'; unrelated.write_text('保留', encoding='utf-8')
            drawing = out/'page-handdrawn.png'
            Image.new('RGB', (9, 9), 'blue').save(drawing)
            # 页数减少后重渲染，不能残留上次的第二页。
            single = Deck(1000, 750); single.slide(); single.text(50, 50, 900, 100, '新版只有一页')
            single.save(root/'一页.pptx')
            shorter = render(root/'一页.pptx', out, scale_to=500, overwrite=True)
            self.assertEqual(len(shorter['pages']), 1)
            self.assertFalse((out/'page-02.png').exists())
            self.assertEqual(unrelated.read_text(encoding='utf-8'), '保留')
            self.assertTrue(drawing.exists())


if __name__ == '__main__':
    main()
