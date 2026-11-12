#!/usr/bin/env python3
"""Build only explicitly allowlisted sources; never package a runtime/library."""
import argparse,hashlib,json,re,sqlite3,zipfile
from pathlib import Path, PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
VERSION='1.1.0'
FORBIDDEN_PARTS={'node_modules','.venv','.runtime','.bootstrap','__pycache__','.pytest_cache','dist','.git','library','capture','backups','evidence'}

def allowlisted(root=ROOT):
    result=[]
    for line in (root/'release-files.txt').read_text().splitlines():
        if not line or line.startswith('#'):continue
        rel=PurePosixPath(line)
        if rel.is_absolute() or '..' in rel.parts or any(x in FORBIDDEN_PARTS for x in rel.parts):raise ValueError('Unsafe release entry: '+line)
        path=root.joinpath(*rel.parts)
        if not path.is_file() or path.is_symlink():raise ValueError('Missing or nonregular release file: '+line)
        if path.suffix in {'.sqlite','.db','.pyc','.log'} or path.name in {'.access-key','.env','runtime.json'}:raise ValueError('Private runtime file: '+line)
        result.append((line,path))
    if len({r[0] for r in result})!=len(result):raise ValueError('Duplicate release path')
    return result

def fingerprints(data):
    texts=set();images=set()
    if not data:return texts,images
    key=data/'.access-key'
    if key.exists():texts.add(key.read_bytes().strip())
    db=data/'library.sqlite'
    if db.exists():
        with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as c:
            coverage=c.execute("SELECT value FROM meta WHERE key='coverage'").fetchone()
            if coverage:
                account=json.loads(coverage[0]).get('account','')
                if account:texts.add(account.encode())
            for row in c.execute('SELECT data FROM posts'):
                record=json.loads(row[0]);caption=record.get('caption','')
                if len(caption)>120:texts.add(caption[:120].encode())
        for path in (data/'thumbnails').glob('*'):
            if path.is_file():images.add(hashlib.sha256(path.read_bytes()).hexdigest())
    return texts,images

def audit(files,private=None):
    texts,images=fingerprints(private);failures=[]
    for name,blob in files:
        if b'/' + b'Users/' in blob or re.search(rb'sk-(?:proj-)?[A-Za-z0-9_-]{35,}',blob):failures.append(name+': machine path or API key pattern')
        if any(value and value in blob for value in texts):failures.append(name+': private library text/key fingerprint')
        if hashlib.sha256(blob).hexdigest() in images:failures.append(name+': private preview fingerprint')
    if failures:raise ValueError('Release privacy audit failed:\n'+'\n'.join(failures))

def build(output,private=None,version=VERSION):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?',version):raise ValueError('Version must be a SemVer-like release identifier.')
    paths=allowlisted();files=[(name,path.read_bytes()) for name,path in paths];audit(files,private)
    output.mkdir(parents=True,exist_ok=True);archives=[]
    for filename,prefix,skill_only in [('saved-again-source-'+version+'.zip','saved-again-public/',False),('saved-again-skill-'+version+'.zip','saved-again/',True)]:
        target=output/filename
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,blob in files:
                if skill_only:
                    if not name.startswith('skills/saved-again/'):continue
                    name=name.removeprefix('skills/saved-again/')
                z.writestr(prefix+name,blob)
        with zipfile.ZipFile(target) as z:
            assert z.testzip() is None
            audit([(name,z.read(name)) for name in z.namelist()],private)
            if skill_only:
                for required in ['SKILL.md','LICENSE','THIRD_PARTY_NOTICES.md','scripts/savedagain.py','assets/dashboard/backend/server.py','assets/dashboard/src/App.jsx','assets/dashboard/package-lock.json','assets/dashboard/public/art/neutral.webp']:
                    if prefix+required not in z.namelist():raise ValueError('Incomplete installed skill: '+required)
        archives.append(target)
    (output/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in archives))
    print('Allowlisted '+str(len(files))+' source files. Repository and both ZIP privacy audits passed.')
    for p in archives:print(p)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'release');p.add_argument('--private-library',type=Path);p.add_argument('--version',default=VERSION);a=p.parse_args()
    build(a.output,a.private_library,a.version)
if __name__=='__main__':main()
