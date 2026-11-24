"""Compare lexical retrieval with real local embeddings; no cloud requests."""
import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from olist import rag
from olist.config import ROOT


def run(split, answers=False):
    fixture=ROOT/'tests/fixtures/rag_benchmark_v1.json'
    suite=json.loads(fixture.read_text(encoding='utf-8'))
    cases=[c for c in suite['cases'] if c['split']==split]
    records=[]
    for mode in ['lexical','hybrid']:
        for case in cases:
            started=time.monotonic()
            result=rag.retrieve(case['question'],mode=mode)
            sections=[s['section'] for s in result['sources']]
            rank=sections.index(case['section'])+1 if case['section'] in sections else None
            records.append({'case_id':case['id'],'mode':mode,'method':result['method'],'expected_answerable':case['section'] is not None,
                'returned_sources':len(sections),'relevant_rank':rank,'sections':sections,'elapsed_ms':round((time.monotonic()-started)*1000,2),
                'scores':[{k:s[k] for k in ['score','lexical_score','semantic_score']} for s in result['sources']]})
    summary={}
    for mode in ['lexical','hybrid']:
        rows=[r for r in records if r['mode']==mode]; positive=[r for r in rows if r['expected_answerable']];negative=[r for r in rows if not r['expected_answerable']]
        summary[mode]={'queries':len(rows),'answerable_queries':len(positive),'unknown_queries':len(negative),
            'hit_at_1':sum(r['relevant_rank']==1 for r in positive)/len(positive),
            'hit_at_3':sum(r['relevant_rank'] is not None for r in positive)/len(positive),
            'mrr_at_3':sum(1/r['relevant_rank'] if r['relevant_rank'] else 0 for r in positive)/len(positive),
            'unknown_refusal_rate':sum(r['returned_sources']==0 for r in negative)/len(negative),
            'latency_p50_ms':statistics.median(r['elapsed_ms'] for r in rows),
            'actual_hybrid_queries':sum(r['method']=='hybrid_sqlite_vec' for r in rows)}
    answer_results=[]
    if answers:
        for case in cases:
            started=time.monotonic();result=rag.answer(case['question'])
            sources={s['id']:s['text'] for s in result['sources']}
            answer_results.append({'case_id':case['id'],'generation':result['generation'],'refused':result['answer']==rag.REFUSAL,
                'citation_count':len(result['citations']),'verbatim_citations':all(q['source_id'] in sources and q['quote'] in sources[q['source_id']] for q in result['citations']),
                'elapsed_ms':round((time.monotonic()-started)*1000,2)})
    git=lambda *args:subprocess.run(['git','-c','safe.directory='+ROOT.as_posix(),*args],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    return {'kind':'local_rag_engineering_evaluation','created_at_utc':datetime.now(timezone.utc).isoformat(),'split':split,
        'suite_version':suite['version'],'suite_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'source_commit':git('rev-parse','HEAD'),
        'worktree_dirty':bool(git('status','--porcelain')),'code_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['olist/rag.py','olist/rag_store.py','scripts/benchmark_rag.py']},
        'index':rag.status(),'summary':summary,'records':records,'answers':answer_results,
        'limits':['Small project-authored demo corpus and labels; not independent business validation.',
                  'Source relevance and verbatim checks do not prove that a quote fully answers a question.',
                  'Fixed lexical-then-hybrid order; latency includes model warming and is not a load test.']}


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',choices=['dev','test'],default='dev')
    parser.add_argument('--answers',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('Kết quả đã tồn tại; chọn tên mới để giữ bằng chứng.')
    result=run(args.split,args.answers)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))
