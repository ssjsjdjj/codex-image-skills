#!/usr/bin/env python3
"""Build a local grouped review from one validated schema-2 report."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_contract import ContractError, make_report, normalize_status, render_markdown, validate_selection

def make_data(manifest, output, status_records=(), title=None):
    return make_report(manifest, output, status_records, title)

def build(manifest,output,status_records=(),title=None):
    output=Path(output)
    data=make_data(manifest,output,status_records,title)
    asset=Path(__file__).resolve().parent.parent/'assets'
    template=(asset/'bulk-review.html').read_text('utf-8');js=(asset/'bulk-review.js').read_text('utf-8')
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    text=template.replace('__REVIEW_DATA__',payload).replace('__REVIEW_SCRIPT__',js)
    output.parent.mkdir(exist_ok=True,parents=True);output.write_text(text,encoding='utf-8')
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--title')
    p.add_argument('--status-record',action='append',default=[],type=Path)
    p.add_argument('--validate-selection',type=Path)
    p.add_argument('--report-json',type=Path)
    p.add_argument('--report-md',type=Path)
    a=p.parse_args()
    try:
        if not a.output and not a.validate_selection:
            p.error('--output is required when building HTML')
        output=a.output or a.manifest.with_name('review.html')
        if a.validate_selection:
            d=make_data(a.manifest,output,a.status_record,a.title)
            result=validate_selection(d,json.loads(a.validate_selection.read_text('utf-8-sig')))
        else:
            d=build(a.manifest,output,a.status_record,a.title)
            result=dict(output=str(output),issues=len(d['issues']),pending_logos=sum(i['group']=='D' and i['feature']=='logo' and i['default_selectable'] for i in d['issues']),dataset_id=d['dataset_id'],revision=d['revision'],diagnostics=d['diagnostics'])
        for path,content in [(a.report_json,json.dumps(d,ensure_ascii=False,indent=2)),(a.report_md,render_markdown(d))]:
            if path:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(content,encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True))
    except (ContractError,OSError,json.JSONDecodeError) as exc:
        p.exit(2,f'Review contract error: {exc}\n')
