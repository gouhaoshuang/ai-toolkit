#!/usr/bin/env python3
"""Render a Markdown reading preview with local assets and optional KaTeX.

Requires markdown-it-py. --katex-module is a local installed Node package;
--chrome optionally saves a headless screenshot. No network or model calls.
"""
import argparse
import html
import json
from pathlib import Path
import re
import subprocess

from markdown_it import MarkdownIt


STYLE = """body{max-width:1120px;margin:35px auto;padding:0 40px;
font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;font-size:16px;
line-height:1.85;color:#20242a}h1{font-size:29px}h2{font-size:24px;margin-top:2em}
h3{font-size:21px}img{max-width:100%;height:auto}table{border-collapse:collapse;
width:100%;font-size:13px;line-height:1.5;margin:20px 0}th,td{padding:8px;
border:1px solid #d8dce2}th{background:#f3f2f9}blockquote{padding:10px 20px;
background:#f5f5fa;border-left:4px solid #8074a8;margin:20px 0}a{color:#55408c}
code{background:#f0f1f4;padding:2px 4px}.katex-display{padding:12px 0;overflow:auto}
pre{white-space:pre-wrap} .table-wrap{overflow-x:auto}"""


def render(markdown, destination, katex_module=None, after=None):
    markdown=Path(markdown).resolve()
    destination=Path(destination).resolve()
    text=markdown.read_text()
    if after:
        start=text.find(after)
        if start<0:raise ValueError('Requested preview start text not found')
        text=text[start:]
    math=[]
    # Keep literal code out of the math parser.
    code=[]
    def protect_code(match):
        code.append(match[0]);return f'CODEPLACEHOLDER{len(code)-1:05}'
    text=re.sub(r'```.*?```|`[^`\n]+`',protect_code,text,flags=re.S)
    def protect_math(match):
        math.append({'tex':match[1] if match[1] is not None else match[2],
                     'display':match[1] is not None})
        return f'MATHPLACEHOLDER{len(math)-1:05}'
    text=re.sub(r'\$\$(.*?)\$\$|(?<!\\)\$(?!\$)([^\n$]+)(?<!\\)\$',protect_math,text,flags=re.S)
    for i,value in enumerate(code):text=text.replace(f'CODEPLACEHOLDER{i:05}',value)
    parsed=MarkdownIt('commonmark',{'html':True}).enable('table').render(text)
    stylesheet=''
    if katex_module:
        module=Path(katex_module).resolve()
        js="""const fs=require('fs'),katex=require(process.argv[1]);
const arr=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(arr.map(m=>katex.renderToString(m.tex,
{displayMode:m.display,throwOnError:true,strict:'ignore'}))));"""
        result=subprocess.run(['node','-e',js,str(module)],input=json.dumps(math),text=True,capture_output=True,check=True)
        expressions=json.loads(result.stdout)
        stylesheet=f'<link rel="stylesheet" href="{html.escape((module/"dist/katex.min.css").as_uri())}">'
    else:
        expressions=[html.escape(m['tex']) for m in math]
    for i,(value,meta) in enumerate(zip(expressions,math)):
        key=f'MATHPLACEHOLDER{i:05}'
        if meta['display']:parsed=parsed.replace('<p>'+key+'</p>',value)
        parsed=parsed.replace(key,value)
    parsed=re.sub(r'(src|href)="([^"#]+)"',lambda m:m[0] if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:',m[2]) else f'{m[1]}="{html.escape((markdown.parent/m[2]).resolve().as_uri())}"',parsed)
    parsed=parsed.replace('<table','<div class="table-wrap"><table').replace('</table>','</table></div>')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'+stylesheet+'<style>'+STYLE+'</style><body>'+parsed+'</body></html>')
    return len(math)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('markdown',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--katex-module',type=Path)
    p.add_argument('--after',help='Start preview at the first exact occurrence of this text')
    p.add_argument('--chrome',type=Path)
    args=p.parse_args()
    count=render(args.markdown,args.out,args.katex_module,args.after)
    if args.chrome:
        subprocess.run([str(args.chrome),'--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
                        '--hide-scrollbars','--window-size=1400,1600','--screenshot='+str(args.out.resolve().with_suffix('.png')),
                        args.out.resolve().as_uri()],check=True,capture_output=True,timeout=60)
    print(json.dumps({'html':str(args.out.resolve()),'math_expressions':count,'screenshot':bool(args.chrome)}))


if __name__=='__main__':main()
