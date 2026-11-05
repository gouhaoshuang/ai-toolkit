"""图片坐标到原生 PowerPoint 元素的辅助库；布局与转录由调用者决定。"""

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile
import math
import os

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (
    XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_TICK_LABEL_POSITION, XL_TICK_MARK,
)
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt


def color(value):
    return RGBColor.from_string(value.lstrip('#').upper())


def insert_fill(sppr, fill):
    """填充必须位于几何之后、线条和效果之前，避免 Office 修复提示。"""
    for child in list(sppr):
        if etree.QName(child).localname in {
            'noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill', 'grpFill',
        }:
            sppr.remove(child)
    index = next((i for i, child in enumerate(sppr) if etree.QName(child).localname
                  in {'ln', 'effectLst', 'effectDag', 'scene3d', 'sp3d', 'extLst'}), len(sppr))
    sppr.insert(index, fill)


def no_effects(shape):
    sppr = shape._element.find(qn('p:spPr'))
    if sppr is not None:
        for tag in ('a:effectLst', 'a:effectDag'):
            for element in sppr.findall(qn(tag)):
                sppr.remove(element)
        effect = OxmlElement('a:effectLst')
        index = next((i for i, ch in enumerate(sppr) if etree.QName(ch).localname
                      in {'scene3d', 'sp3d', 'extLst'}), len(sppr))
        sppr.insert(index, effect)
    for ref in shape._element.iter(qn('a:effectRef')):
        ref.set('idx', '0')


def scale_typography(root, factor):
    """显式字体、行距、内边距、线宽和表格网格需要与几何同步缩放。"""
    for el in root.iter():
        local = etree.QName(el).localname
        attrs = []
        if local in {'rPr', 'defRPr', 'endParaRPr'}:
            attrs = ['sz']
        elif local == 'spcPts':
            attrs = ['val']
        elif local in {'ln', 'gridCol'}:
            attrs = ['w']
        elif local == 'tr':
            attrs = ['h']
        elif local in {'bodyPr', 'tcPr'}:
            attrs = ['lIns', 'rIns', 'tIns', 'bIns', 'marL', 'marR', 'marT', 'marB']
        elif local == 'pPr':
            attrs = ['marL', 'marR', 'indent', 'defTabSz']
        for attr in attrs:
            if el.get(attr) is not None:
                el.set(attr, str(round(int(el.get(attr)) * factor)))


def walk_shapes(shapes):
    for shape in shapes:
        if shape.shape_type == 6:
            yield from walk_shapes(shape.shapes)
        else:
            yield shape


class Deck:
    def __init__(self, width, height, font='Microsoft YaHei', pixels_per_inch=100):
        if min(width, height, pixels_per_inch) <= 0:
            raise ValueError('画布尺寸与 pixels_per_inch 必须为正数')
        self.width, self.height = width, height
        self.ppi, self.font = pixels_per_inch, font
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = self.u(width), self.u(height)
        self.current = self.shapes = None

    def u(self, value):
        return Inches(value / self.ppi)

    def pt(self, value):
        return Pt(value * 72 / self.ppi)

    def slide(self, background='FFFFFF'):
        self.current = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.shapes = self.current.shapes
        self.current.background.fill.solid()
        self.current.background.fill.fore_color.rgb = color(background)
        return self.current

    @contextmanager
    def group(self, name):
        parent = self.shapes
        obj = parent.add_group_shape()
        obj.name, self.shapes = name, obj.shapes
        try:
            yield obj
        finally:
            self.shapes = parent

    def box(self, x, y, w, h, fill='FFFFFF', stroke=None, radius=0, width=1, name=None):
        if min(w, h) <= 0:
            raise ValueError('方框宽高必须为正数')
        kind = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
        obj = self.shapes.add_shape(kind, self.u(x), self.u(y), self.u(w), self.u(h))
        obj.name = name or '可编辑方框'
        if radius:
            obj.adjustments[0] = min(.49, radius / min(w, h))
        if fill:
            obj.fill.solid()
            obj.fill.fore_color.rgb = color(fill)
        else:
            obj.fill.background()
        if stroke:
            obj.line.color.rgb, obj.line.width = color(stroke), self.pt(width)
        else:
            obj.line.fill.background()
            for ref in obj._element.iter(qn('a:lnRef')):
                ref.set('idx', '0')
        no_effects(obj)
        return obj

    def gradient(self, shape, first, last, angle=90):
        fill = OxmlElement('a:gradFill')
        stops = OxmlElement('a:gsLst')
        for position, value in [('0', first), ('100000', last)]:
            stop = OxmlElement('a:gs'); stop.set('pos', position)
            rgb = OxmlElement('a:srgbClr'); rgb.set('val', str(color(value)))
            stop.append(rgb); stops.append(stop)
        fill.append(stops)
        direction = OxmlElement('a:lin')
        direction.set('ang', str(round((angle % 360) * 60000)))
        direction.set('scaled', '1'); fill.append(direction)
        insert_fill(shape._element.find(qn('p:spPr')), fill)
        return shape

    def _style_run(self, run, style):
        run.font.name = style.get('font', self.font)
        run.font.size = self.pt(style.get('size', 24))
        run.font.bold, run.font.italic = style.get('bold', False), style.get('italic', False)
        run.font.color.rgb = color(style.get('color', '172231'))
        rpr = run._r.get_or_add_rPr()
        if 'baseline' in style:
            rpr.set('baseline', str(style['baseline']))
        for tag in ('ea', 'cs'):
            face = rpr.find(qn('a:' + tag))
            if face is None:
                face = OxmlElement('a:' + tag); rpr.append(face)
            face.set('typeface', style.get('font', self.font))

    def text(self, x, y, w, h, text, size=24, color='172231', bold=False,
             align='left', font=None, wrap=False, line_spacing=1.2):
        obj = self.shapes.add_textbox(self.u(x), self.u(y), self.u(w), self.u(h))
        tf = obj.text_frame; tf.clear(); tf.word_wrap = wrap; tf.auto_size = None
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.TOP
        base = dict(size=size, color=color, bold=bold, font=font or self.font)
        # 显式换行变成段落；富文本中的每一段样式仍独立可编辑。
        runs = [{'text': text}] if isinstance(text, str) else text
        paragraph = tf.paragraphs[0]
        for spec in runs:
            parts = spec['text'].split('\n')
            for i, part in enumerate(parts):
                if i:
                    paragraph = tf.add_paragraph()
                paragraph.alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER,
                                       'right': PP_ALIGN.RIGHT}[align]
                paragraph.space_before = paragraph.space_after = Pt(0)
                paragraph.line_spacing = self.pt(size * line_spacing)
                ppr = paragraph._p.get_or_add_pPr()
                ppr.set('marL', '0'); ppr.set('indent', '0')
                if ppr.find(qn('a:buNone')) is None:
                    ppr.append(OxmlElement('a:buNone'))
                run = paragraph.add_run(); run.text = part
                self._style_run(run, base | spec)
        obj.name = ''.join(item['text'] for item in runs).replace('\n', ' ')[:80]
        return obj

    def route(self, points, color='172231', width=1.5, arrow=True, dashed=False):
        if len(points) < 2:
            raise ValueError('路径至少需要两个点')
        results = []
        for i, (a, b) in enumerate(zip(points, points[1:])):
            obj = self.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, self.u(a[0]),
                                           self.u(a[1]), self.u(b[0]), self.u(b[1]))
            obj.line.color.rgb, obj.line.width = globals()['color'](color), self.pt(width)
            if dashed:
                obj.line.dash_style = MSO_LINE_DASH_STYLE.DASH
            if arrow and i == len(points) - 2:
                tip = OxmlElement('a:tailEnd')
                for key, value in [('type', 'triangle'), ('w', 'med'), ('len', 'med')]:
                    tip.set(key, value)
                obj.line._get_or_add_ln().append(tip)
            no_effects(obj); results.append(obj)
        return results

    def bezier(self, start, control1, control2, end, color='172231', width=1.5, arrow=True):
        points = [start, control1, control2, end]
        x, y = min(p[0] for p in points), min(p[1] for p in points)
        w = max(p[0] for p in points) - x or .01
        h = max(p[1] for p in points) - y or .01
        obj = self.box(x, y, w, h, fill=None, stroke=color, width=width)
        sppr = obj._element.find(qn('p:spPr'))
        sppr.remove(sppr.find(qn('a:prstGeom')))
        geom = OxmlElement('a:custGeom')
        for tag in ['avLst', 'gdLst', 'ahLst', 'cxnLst']:
            geom.append(OxmlElement('a:' + tag))
        rect = OxmlElement('a:rect')
        for key, value in [('l', '0'), ('t', '0'), ('r', 'w'), ('b', 'h')]:
            rect.set(key, value)
        geom.append(rect); paths = OxmlElement('a:pathLst'); path = OxmlElement('a:path')
        path.set('w', str(round(w * 1000))); path.set('h', str(round(h * 1000)))
        path.set('fill', 'none')
        for tag, pts in [('moveTo', [start]), ('cubicBezTo', [control1, control2, end])]:
            cmd = OxmlElement('a:' + tag)
            for px, py in pts:
                point = OxmlElement('a:pt')
                point.set('x', str(round((px - x) * 1000)))
                point.set('y', str(round((py - y) * 1000))); cmd.append(point)
            path.append(cmd)
        paths.append(path); geom.append(paths); sppr.insert(1, geom)
        if arrow:
            tip = OxmlElement('a:tailEnd'); tip.set('type', 'triangle')
            obj.line._get_or_add_ln().append(tip)
        return obj

    def crop_image(self, source, box, dest, name='局部插图'):
        with Image.open(source) as image:
            image.load()
            left, top, right, bottom = box
            if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                raise ValueError('裁切范围必须位于源图内且面积为正')
            stream = BytesIO(); image.crop(box).save(stream, format='PNG'); stream.seek(0)
        x, y, w, h = dest
        if min(w, h) <= 0:
            raise ValueError('图片显示尺寸必须为正')
        obj = self.shapes.add_picture(stream, self.u(x), self.u(y), self.u(w), self.u(h))
        obj.name = name; return obj

    def bar_chart(self, x, y, w, h, categories, values, colors, maximum,
                  major, number_format='0.0', size=20):
        if not categories or not len(categories) == len(values) == len(colors):
            raise ValueError('类别、数值和颜色必须等长且非空')
        if not math.isfinite(maximum) or maximum <= 0 or not math.isfinite(major) or major <= 0:
            raise ValueError('轴最大值与主刻度必须是正有限数')
        if any(not math.isfinite(v) or not 0 <= v <= maximum for v in values):
            raise ValueError('此横向条形图辅助函数只接受轴范围内的非负有限值')
        data = CategoryChartData(); data.categories = categories
        data.add_series('数据', values, number_format=number_format)
        chart = self.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, self.u(x), self.u(y),
                                     self.u(w), self.u(h), data).chart
        chart.has_title = chart.has_legend = False
        chart.font.name = self.font; chart.font.size = self.pt(size)
        plot = chart.plots[0]; plot.gap_width = 55; plot.has_data_labels = True
        labels = plot.data_labels; labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        labels.number_format, labels.number_format_is_linked = number_format, False
        labels.font.name = self.font; labels.font.size = self.pt(size)
        for pt, col in zip(chart.series[0].points, colors):
            pt.format.fill.solid(); pt.format.fill.fore_color.rgb = color(col)
            pt.format.line.fill.background()
        ca, va = chart.category_axis, chart.value_axis
        ca.reverse_order = True; ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        ca._element.find(qn('c:crosses')).set('val', 'autoZero')
        va._element.find(qn('c:crosses')).set('val', 'max')
        for tag in ['tickLblSkip', 'tickMarkSkip']:
            element = OxmlElement('c:' + tag); element.set('val', '1'); ca._element.append(element)
        va.minimum_scale, va.maximum_scale, va.major_unit = 0, maximum, major
        va.tick_label_position = XL_TICK_LABEL_POSITION.HIGH
        va.tick_labels.number_format = '0'; va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = color('E1EAF4')
        for axis in [ca, va]:
            axis.major_tick_mark = axis.minor_tick_mark = XL_TICK_MARK.NONE
            axis.tick_labels.font.name = self.font; axis.tick_labels.font.size = self.pt(size)
            axis.format.line.fill.background()
        for rpr in chart._chartSpace.iter(qn('a:defRPr')):
            for tag in ['ea', 'cs']:
                face = OxmlElement('a:' + tag); face.set('typeface', self.font); rpr.append(face)
        for body in chart._chartSpace.iter(qn('a:bodyPr')):
            body.set('wrap', 'none')
        for parent in [chart._chartSpace, chart._chartSpace.chart.plotArea]:
            sppr = OxmlElement('c:spPr'); sppr.append(OxmlElement('a:noFill'))
            ln = OxmlElement('a:ln'); ln.append(OxmlElement('a:noFill')); sppr.append(ln)
            sppr.append(OxmlElement('a:effectLst')); parent.append(sppr)
        return chart

    def inset(self, slide, scale=.9):
        if not math.isfinite(scale) or not 0 < scale <= 1:
            raise ValueError('居中缩放比例必须大于 0 且不超过 1')
        dx, dy = (1 - scale) * self.prs.slide_width / 2, (1 - scale) * self.prs.slide_height / 2

        def transform(shapes, top_level):
            for shape in shapes:
                el = shape._element
                xf = el.find('p:grpSpPr/a:xfrm', el.nsmap) if shape.shape_type == 6 else (
                    el.find('p:xfrm', el.nsmap) if shape.has_table or shape.has_chart
                    else el.find('p:spPr/a:xfrm', el.nsmap))
                if xf is not None:
                    for name in ['off', 'chOff', 'ext', 'chExt']:
                        child = xf.find(qn('a:' + name))
                        if child is None:
                            continue
                        for attr in (['x', 'y'] if name.endswith('Off') or name == 'off' else ['cx', 'cy']):
                            shift = (dx if attr == 'x' else dy) if name == 'off' and top_level else 0
                            child.set(attr, str(round(int(child.get(attr)) * scale + shift)))
                if shape.shape_type == 6:
                    transform(shape.shapes, False)

        transform(slide.shapes, True)
        scale_typography(slide._element, scale)
        seen = set()
        for shape in walk_shapes(slide.shapes):
            if shape.has_chart and id(shape.chart.part) not in seen:
                scale_typography(shape.chart._chartSpace, scale); seen.add(id(shape.chart.part))

    def save(self, output):
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        # 同目录原子替换，失败时不留下半写入的成品。
        with NamedTemporaryFile(dir=output.parent, suffix='.pptx', delete=False) as file:
            temp = Path(file.name)
        try:
            self.prs.save(temp)
            with ZipFile(temp) as z:
                items = [(info, z.read(info.filename)) for info in z.infolist()]
            with ZipFile(temp, 'w') as z:
                for info, data in items:
                    if info.filename.startswith(('ppt/theme/', 'ppt/slideMasters/', 'ppt/slideLayouts/')) and info.filename.endswith('.xml'):
                        root = etree.fromstring(data)
                        for tag in ['latin', 'ea', 'cs']:
                            for face in root.iter(qn('a:' + tag)):
                                face.set('typeface', self.font)
                        data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                    z.writestr(info, data)
            os.replace(temp, output)
        finally:
            temp.unlink(missing_ok=True)
        return output
