#!/usr/bin/env python3
"""Compare decimal-value coverage in original LaTeX and translated tables.

This is an audit aid, not a proof of cell alignment or translation correctness.
Pass only main-text source files from the exact PDF version, excluding backups.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def uncomment(text):
    output=[]
    for line in text.splitlines():
        for i,ch in enumerate(line):
            if ch!='%':continue
            j=i-1
            while j>=0 and line[j]=='\\':j-=1
            if (i-j-1)%2==0:
                line=line[:i]
                break
        output.append(line)
    return '\n'.join(output)


def values(text):
    return Counter(x.lstrip('+') for x in re.findall(r'(?<![\w.])[-+]?\d+\.\d+(?![\w.])',text))


def audit(tex,markdown):
    tex=uncomment(tex).split('\\appendix')[0]
    tables=re.findall(r'\\begin\{table\*?\}(.*?)\\end\{table\*?\}',tex,re.S)
    source='\n'.join(line for table in tables for line in table.splitlines() if '&' in line)
    markdown=markdown.split('## 参考文献')[0]
    target='\n'.join(re.findall(r'<table\b.*?</table>',markdown,re.S))+'\n'+'\n'.join(line for line in markdown.splitlines() if line.startswith('|'))
    a,b=values(source),values(target)
    return {'source_tables':len(tables),'source_decimal_values':sum(a.values()),'target_decimal_values':sum(b.values()),
            'missing_values':dict(a-b),'extra_values':dict(b-a),'coverage_passed':not bool(a-b),
            'scope':'Decimal-value multisets only; leading plus signs ignored, minus signs preserved. Does not verify cell alignment or integers. Source macro expansions may require review.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tex',type=Path,action='append',required=True)
    p.add_argument('--markdown',type=Path,required=True)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=audit('\n'.join(x.read_text() for x in args.tex),args.markdown.read_text())
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text,end='')
    if not result['coverage_passed']:raise SystemExit(1)


if __name__=='__main__':main()
