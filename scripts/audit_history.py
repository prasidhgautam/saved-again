#!/usr/bin/env python3
"""Audit every Git blob plus the working tree without printing sensitive content."""
import argparse, hashlib, json, re, sqlite3, subprocess, sys
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES={'.env','.access-key','runtime.json','cloud.json'}
FORBIDDEN_SUFFIXES={'.sqlite','.sqlite3','.db','.log','.pem','.key','.p12','.pfx'}
TEXT_PATTERNS={
    'absolute macOS user path':re.compile(rb'/' rb'Users/[A-Za-z0-9._-]+/'),
    'absolute Linux user path':re.compile(rb'/home/[A-Za-z0-9._-]+/'),
    'OpenAI-style API key':re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{35,}'),
    'AWS access key':re.compile(rb'AKIA[0-9A-Z]{16}'),
    'GitHub token':re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
    'Cloudflare API token assignment':re.compile(rb'(?i)(?:cloudflare|cf)[_-]?(?:api[_-]?)?token\s*[:=]\s*["\']?[A-Za-z0-9_-]{20,}'),
    'private key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
}
CLOUDFLARE_ID=re.compile(rb'(?i)(account_id|zone_id|database_id)\s*[:=]\s*["\']?([0-9a-f-]{32,36})')

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)

def private_fingerprints(data):
    texts=set();images=set()
    if not data:return texts,images
    key=data/'.access-key'
    if key.is_file():texts.add(key.read_bytes().strip())
    database=data/'library.sqlite'
    if database.is_file():
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as connection:
            tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'meta' in tables:
                row=connection.execute("SELECT value FROM meta WHERE key='coverage'").fetchone()
                if row:
                    account=json.loads(row[0]).get('account','')
                    if account:texts.add(account.encode())
            if 'posts' in tables:
                for row in connection.execute('SELECT data FROM posts'):
                    caption=json.loads(row[0]).get('caption','')
                    if len(caption)>120:texts.add(caption[:120].encode())
        for path in (data/'thumbnails').glob('*'):
            if path.is_file():images.add(hashlib.sha256(path.read_bytes()).hexdigest())
    return texts,images

def inspect_blob(path,blob,texts=frozenset(),images=frozenset()):
    findings=[];parts=PurePosixPath(path).parts;name=PurePosixPath(path).name
    if name in FORBIDDEN_NAMES or PurePosixPath(path).suffix.lower() in FORBIDDEN_SUFFIXES:
        findings.append('forbidden private/runtime filename')
    if any(part in {'library','capture','backups'} for part in parts):findings.append('private runtime directory')
    for label,pattern in TEXT_PATTERNS.items():
        if pattern.search(blob):findings.append(label)
    for match in CLOUDFLARE_ID.finditer(blob):
        identifier=match.group(2).replace(b'-',b'')
        if identifier.strip(b'0'):findings.append('committed Cloudflare resource identifier')
    if any(value and value in blob for value in texts):findings.append('private library text/key fingerprint')
    if hashlib.sha256(blob).hexdigest() in images:findings.append('private preview fingerprint')
    return sorted(set(findings))

def history_blobs():
    seen=set()
    commits=git('rev-list','--all').decode().splitlines()
    for commit in commits:
        entries=git('ls-tree','-r','-z',commit).split(b'\0')
        for entry in entries:
            if not entry:continue
            metadata,path=entry.split(b'\t',1);kind,object_id=metadata.split()[1:3]
            if kind!=b'blob' or (object_id,path) in seen:continue
            seen.add((object_id,path));yield commit,path.decode('utf-8','surrogateescape'),git('cat-file','blob',object_id.decode())

def working_tree_blobs():
    entries=git('ls-files','-z','--cached','--others','--exclude-standard').split(b'\0')
    for raw in entries:
        if not raw:continue
        path=raw.decode('utf-8','surrogateescape');source=ROOT/path
        if source.is_file() and not source.is_symlink():yield 'WORKTREE',path,source.read_bytes()

def audit(private=None,include_worktree=True):
    texts,images=private_fingerprints(private);findings=[];scanned=0
    streams=[history_blobs()]
    if include_worktree:streams.append(working_tree_blobs())
    for stream in streams:
        for revision,path,blob in stream:
            scanned+=1
            for reason in inspect_blob(path,blob,texts,images):findings.append({'revision':revision,'path':path,'reason':reason})
    return {'commits':len(git('rev-list','--all').decode().splitlines()),'blobs_scanned':scanned,'findings':findings}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-library',type=Path)
    parser.add_argument('--history-only',action='store_true')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args();report=audit(args.private_library,not args.history_only)
    if args.json:print(json.dumps(report,indent=2))
    else:
        print(f"Scanned {report['commits']} commits and {report['blobs_scanned']} historical/working-tree blobs.")
        for item in report['findings']:print(f"{item['revision'][:12]} {item['path']}: {item['reason']}")
        print('Privacy audit passed.' if not report['findings'] else 'Privacy audit failed.')
    return 1 if report['findings'] else 0

if __name__=='__main__':sys.exit(main())
