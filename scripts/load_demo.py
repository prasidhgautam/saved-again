#!/usr/bin/env python3
"""Load invented records into a separate, empty running demo library."""
import argparse,json,urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);args=p.parse_args();data=args.data.expanduser().resolve()
    state=json.loads((data/'runtime.json').read_text());key=(data/'.access-key').read_text().strip();origin='http://127.0.0.1:'+str(state['port'])
    def api(path,body=None):
        request=urllib.request.Request(origin+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as r:return json.load(r)
    library=api('library')
    if library['total']:raise SystemExit('Demo loader requires an empty library; use a separate workspace.')
    fixture=json.loads((Path(__file__).resolve().parents[1]/'docs/demo.json').read_text())
    for category in fixture.get('categories',[]):api('categories',category)
    result=api('import',{k:v for k,v in fixture.items() if k!='categories'})
    print('Loaded synthetic demo only:',result['total'],'invented records. No Instagram requests made.')
if __name__=='__main__':main()
