#!/usr/bin/env python3
"""发现图片、检查 PPT 可编辑结构、导出实际页面预览。"""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}


def natural_key(path):
    return [int(s) if s.isdigit() else s.casefold() for s in re.split(r'(\d+)', path.name)]


def inventory(path):
    from PIL import Image
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    files = [path] if path.is_file() else sorted(
        (p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=natural_key)
    result = []
    for file in files:
        with Image.open(file) as im:
            result.append(dict(path=str(file), width=im.width, height=im.height,
                               mode=im.mode, frames=getattr(im, 'n_frames', 1)))
    return result


def doctor():
    result = {
        'python': sys.version.split()[0],
        'modules': {name: importlib.util.find_spec(name) is not None for name in ['pptx', 'PIL', 'lxml']},
        'tools': {name: shutil.which(name) for name in ['libreoffice', 'soffice', 'pdftoppm', 'fc-match']},
    }
    fc = result['tools']['fc-match']
    if fc:
        p = subprocess.run([fc, '-f', '%{family}\n', 'Microsoft YaHei'],
                           capture_output=True, text=True, timeout=10, check=True)
        result['yahei_actual_match'] = p.stdout.strip()
    return result


def audit(path):
    from lxml import etree
    from pptx import Presentation
    from pptx.oxml.ns import qn

    path = Path(path).resolve()
    ranks = dict(xfrm=0, prstGeom=1, custGeom=1, noFill=2, solidFill=2, gradFill=2,
                 blipFill=2, pattFill=2, grpFill=2, ln=3, effectLst=4, effectDag=4,
                 scene3d=5, sp3d=6, extLst=7)
    xml_errors = []
    with ZipFile(path) as z:
        corrupt = z.testzip()
        if corrupt:
            raise ValueError('ZIP 校验失败: ' + corrupt)
        for name in z.namelist():
            if name.endswith('.xml'):
                tree = etree.fromstring(z.read(name))
                if name.startswith('ppt/slides/slide'):
                    for sp in tree.iter(qn('p:spPr')):
                        order = [ranks[etree.QName(ch).localname] for ch in sp
                                 if etree.QName(ch).localname in ranks]
                        if order != sorted(order):
                            xml_errors.append(name + ': p:spPr 子节点顺序异常')
        embedded = [n for n in z.namelist() if n.startswith('ppt/embeddings/')]

    prs = Presentation(path); width, height = prs.slide_width, prs.slide_height
    slides = []
    for index, slide in enumerate(prs.slides, 1):
        result = dict(page=index, groups=0, native_elements=0, text=[], images=[],
                      charts=[], tables=[], out_of_bounds=[], declared_fonts=[],
                      sub_or_superscript_runs=0)
        fonts = set()

        def visit(shapes, sx=1., sy=1., tx=0., ty=0.):
            for shape in shapes:
                left, top = tx + sx * shape.left, ty + sy * shape.top
                w, h = sx * shape.width, sy * shape.height
                if shape.shape_type == 6:
                    result['groups'] += 1
                    xf = shape._element.find('p:grpSpPr/a:xfrm', shape._element.nsmap)
                    off, ext = xf.find(qn('a:chOff')), xf.find(qn('a:chExt'))
                    cx, cy = int(ext.get('cx')), int(ext.get('cy'))
                    gx, gy = w / cx if cx else 1, h / cy if cy else 1
                    visit(shape.shapes, gx, gy,
                          left - gx * int(off.get('x')), top - gy * int(off.get('y')))
                    continue
                if min(left, top) < -2 or left + w > width + 2 or top + h > height + 2:
                    result['out_of_bounds'].append(shape.name)
                if shape.shape_type == 13:
                    result['images'].append(dict(
                        name=shape.name, embedded_pixels=list(shape.image.size),
                        display_area_fraction=round(w * h / (width * height), 5),
                        crop=[shape.crop_left, shape.crop_top, shape.crop_right, shape.crop_bottom]))
                else:
                    result['native_elements'] += 1
                if shape.has_text_frame and shape.text:
                    result['text'].append(shape.text)
                if shape.has_table:
                    result['tables'].append([[cell.text for cell in row.cells] for row in shape.table.rows])
                roots = [shape._element]
                if shape.has_chart:
                    c = shape.chart; roots.append(c._chartSpace)
                    chart_result = {'plots': []}
                    for plot in c.plots:
                        chart_result['plots'].append({
                            'categories': [cat.label for cat in plot.categories],
                            'series': [{'name': series.name, 'values': list(series.values)} for series in plot.series],
                            'data_label_format': plot.data_labels.number_format if plot.has_data_labels else None,
                        })
                    result['charts'].append(chart_result)
                for root in roots:
                    for tag in ['latin', 'ea', 'cs']:
                        fonts.update(e.get('typeface') for e in root.iter(qn('a:' + tag)) if e.get('typeface'))
                    result['sub_or_superscript_runs'] += sum(e.get('baseline') is not None
                                                             for e in root.iter(qn('a:rPr')))
        visit(slide.shapes)
        result['declared_fonts'] = sorted(fonts)
        result['review_hints'] = []
        if any(im['display_area_fraction'] > .8 for im in result['images']):
            result['review_hints'].append('大面积图片：人工确认是否合理背景/插画，不能据此声称整页可编辑')
        if result['out_of_bounds']:
            result['review_hints'].append('发现越界几何；旋转/阴影未计入边界，需看实际预览')
        slides.append(result)
    return dict(file=str(path), pages=len(slides), width_emu=width, height_emu=height,
                zip_valid=True, shape_xml_order_errors=xml_errors, embedded_objects=embedded,
                slides=slides, limitations='结构审计不验证文字准确性、字体是否安装、文本溢出或视觉还原度；组旋转未计入边界。')


def render(path, out_dir, scale_to=1800, overwrite=False, timeout=180):
    source, out = Path(path).resolve(), Path(out_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if scale_to <= 0 or timeout <= 0:
        raise ValueError('scale-to 与 timeout 必须为正数')
    lo = shutil.which('libreoffice') or shutil.which('soffice')
    pdftoppm = shutil.which('pdftoppm')
    if not lo or not pdftoppm:
        raise RuntimeError('预览需要 LibreOffice/soffice 和 Poppler pdftoppm；不会使用原图伪造预览')
    out.mkdir(parents=True, exist_ok=True)
    pages = [p for p in out.glob('page-*.png') if re.fullmatch(r'page-\d+\.png', p.name)]
    managed = [out / 'preview.pdf', out / 'render.json', *pages]
    if not overwrite and any(p.exists() for p in managed):
        raise FileExistsError('预览目标已有同名产物；请选择新目录或显式 --overwrite')
    # 独立 profile 避免连接到桌面 Office，临时产物也不会混入旧预览。
    with TemporaryDirectory(prefix='pptx-preview-') as temp:
        work = Path(temp); profile = work / 'profile'; converted = work / 'converted'
        converted.mkdir()
        commands = [
            [lo, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--convert-to',
             'pdf', '--outdir', str(converted), str(source)],
        ]
        p = subprocess.run(commands[0], capture_output=True, text=True, timeout=timeout)
        pdf = converted / (source.stem + '.pdf')
        if p.returncode or not pdf.exists():
            raise RuntimeError('LibreOffice 未生成 PDF: ' + (p.stderr or p.stdout)[-1500:])
        commands.append([pdftoppm, '-png', '-scale-to', str(scale_to), str(pdf), str(work / 'page')])
        p = subprocess.run(commands[1], capture_output=True, text=True, timeout=timeout)
        images = sorted(work.glob('page-*.png'), key=natural_key)
        if p.returncode or not images:
            raise RuntimeError('PDF 页面渲染失败: ' + (p.stderr or p.stdout)[-1500:])
        from pptx import Presentation
        if len(images) != len(Presentation(source).slides):
            raise RuntimeError('预览页数与 PPT 不一致，拒绝复用旧产物')
        # 全部转换成功后才替换受管理文件；不删除目录内其他用户文件。
        for target in managed:
            target.unlink(missing_ok=True)
        shutil.copy2(pdf, out / 'preview.pdf')
        paths = []
        for i, im in enumerate(images, 1):
            target = out / f'page-{i:02}.png'; shutil.copy2(im, target); paths.append(str(target))
    result = dict(source=str(source), pdf=str(out / 'preview.pdf'), pages=paths,
                  renderer='LibreOffice + Poppler', visual_review_performed=False)
    (out / 'render.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    inv = sub.add_parser('inventory'); inv.add_argument('path')
    check = sub.add_parser('audit'); check.add_argument('path'); check.add_argument('--out')
    preview = sub.add_parser('render'); preview.add_argument('path')
    preview.add_argument('--out-dir', required=True); preview.add_argument('--overwrite', action='store_true')
    preview.add_argument('--scale-to', type=int, default=1800); preview.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    try:
        if args.command == 'doctor': result = doctor()
        elif args.command == 'inventory': result = inventory(args.path)
        elif args.command == 'audit': result = audit(args.path)
        else: result = render(args.path, args.out_dir, args.scale_to, args.overwrite, args.timeout)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.command == 'audit' and args.out:
            target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + '\n', encoding='utf-8')
        print(text)
        return 1 if args.command == 'audit' and result['shape_xml_order_errors'] else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
