#!/usr/bin/env python3
"""Portable local manager. No Instagram credentials, scraping or AI service calls."""
import argparse, getpass, hashlib, importlib.util, json, os, re, shutil, signal, socket, sqlite3, subprocess, sys, tarfile, tempfile, time, urllib.request, urllib.error, uuid
from pathlib import Path, PurePosixPath

SKILL=Path(__file__).resolve().parents[1]
BUNDLE=SKILL/'assets'/'dashboard'
VERSION='1.1.0'
MODEL_MANIFEST=SKILL/'references'/'models-manifest.json'

def fail(message):raise RuntimeError(message)
def python_in(app):return app/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
def paths(args):
    app=(args.workspace.expanduser().resolve()/'app')
    data=(args.data.expanduser().resolve() if args.data else args.workspace.expanduser().resolve()/'library')
    if data==app or app in data.parents or data in app.parents:fail('Application and library directories must be separate, without nesting.')
    return app,data

def private(path):
    if os.name!='nt':path.chmod(0o700 if path.is_dir() else 0o600)
def read_json(path,default=None):return json.loads(path.read_text()) if path.exists() else default

def environment(node=None):
    env=os.environ.copy()
    if node:env['PATH']=str(Path(node).resolve().parent)+os.pathsep+env.get('PATH','')
    return env

def command_version(command):
    path=shutil.which(command)
    if not path:return None,None
    try:return path,subprocess.check_output([path,'--version'],text=True,stderr=subprocess.STDOUT,timeout=10).strip().splitlines()[0]
    except (OSError,subprocess.SubprocessError):return path,None

def file_sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def voice_studio_status():
    base=(os.environ.get('SAVEDAGAIN_VOICESTUDIO_URL') or 'http://localhost:3900').rstrip('/')
    result={'url':base,'status':'unavailable','transcription_contract':False}
    try:
        with urllib.request.urlopen(base+'/health',timeout=2) as response:
            result['health_status']=response.status
        with urllib.request.urlopen(base+'/openapi.json',timeout=3) as response:
            schema=json.load(response)
        result['transcription_contract']='/v1/audio/transcriptions' in schema.get('paths',{})
        result['status']='ready' if result['transcription_contract'] else 'schema_missing_transcription'
    except (OSError,ValueError,urllib.error.URLError) as error:result['detail']=str(error)
    return result

def configured_models():
    manifest=read_json(MODEL_MANIFEST,{'models':[]});results=[]
    for model in manifest.get('models',[]):
        status={'id':model['id'],'purpose':model['purpose'],'required':False,'status':'not_configured'}
        variable=model.get('environment')
        configured=os.environ.get(variable,'') if variable else ''
        if configured:
            path=Path(configured).expanduser()
            status.update(environment=variable,path=str(path),status='ready' if path.exists() else 'missing')
            expected=model.get('expected_file')
            if path.exists() and expected:
                candidate=path/expected if path.is_dir() else path
                status['status']='ready' if candidate.is_file() else 'missing_expected_file'
                if candidate.is_file() and model.get('sha256'):
                    digest=file_sha256(candidate)
                    status.update(sha256=digest,status='ready' if digest==model['sha256'] else 'checksum_mismatch')
        elif model.get('runtime')=='ollama':
            status['status']='disabled' if os.environ.get('SAVEDAGAIN_OLLAMA','off').lower() not in {'1','true','on'} else 'runtime_check_required'
        results.append(status)
    return {'manifest_version':manifest.get('version'),'models':results}

def emit_report(report,as_json=False):
    if as_json:print(json.dumps(report,indent=2));return
    for name,value in report.items():
        if isinstance(value,dict):print(name+': '+str(value.get('status',value)))
        elif isinstance(value,list):
            print(name+':')
            for item in value:print('  '+item.get('id','item')+': '+item.get('status','unknown'))
        else:print(name+': '+str(value))

def doctor(args):
    app,data=paths(args);node_path,node_version=command_version('node');npm_path,npm_version=command_version('npm')
    node_ok=False
    if node_version:
        try:node_ok=int(re.search(r'(\d+)',node_version).group(1))>=24
        except (AttributeError,ValueError):pass
    report={
        'python':{'status':'ready' if sys.version_info>=(3,11) else 'upgrade_required','version':sys.version.split()[0],'executable':sys.executable},
        'node':{'status':'ready' if node_ok else ('upgrade_required' if node_path else 'missing'),'version':node_version,'path':node_path},
        'npm':{'status':'ready' if npm_path else 'missing','version':npm_version,'path':npm_path},
        'ffmpeg':{'status':'ready' if command_version('ffmpeg')[0] else 'missing_optional'},
        'ffprobe':{'status':'ready' if command_version('ffprobe')[0] else 'missing_optional'},
        'application':{'status':'ready' if python_in(app).exists() and (app/'dist/client/index.html').exists() else 'not_set_up','path':str(app)},
        'library':{'status':'ready' if data.exists() and os.access(data,os.W_OK) else ('not_created' if not data.exists() else 'not_writable'),'path':str(data)},
        'voice_studio':voice_studio_status(),
        'models':configured_models()['models'],
        'cloud':{'status':'configured' if (data/'cloud.json').exists() else 'not_configured'}
    }
    emit_report(report,args.json)
    required=(report['python']['status']=='ready' and report['node']['status']=='ready' and report['npm']['status']=='ready')
    return 0 if required else 1

def models_status(args):
    report=configured_models();emit_report(report,args.json)
    return 1 if any(item['status'] in {'missing','missing_expected_file','checksum_mismatch'} for item in report['models']) else 0

def cloud_template(args):
    app,_=paths(args);source=BUNDLE/'wrangler.example.toml'
    if not source.exists():fail('The Cloudflare template is missing from this SavedAgain package.')
    try:database_id=str(uuid.UUID(args.database_id))
    except ValueError:fail('D1 database ID must be a UUID copied from `wrangler d1 create`.')
    if args.output is None and not (app/'.savedagain-app.json').exists():fail('Run setup before generating the installed app configuration, or select an explicit --output for a source checkout.')
    output=(args.output.expanduser().resolve() if args.output else app/'wrangler.toml')
    if output.exists() and not args.force:fail('Refusing to overwrite '+str(output)+'. Use --force only after reviewing the existing file.')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(source.read_text().replace('00000000-0000-0000-0000-000000000000',database_id))
    print('Wrote Cloudflare configuration to '+str(output)+'. Secrets are still configured separately with Wrangler.')

def setup(args):
    app,data=paths(args)
    if sys.version_info<(3,11):fail('Python 3.11 or newer is required. Run this script with python3.11 (or a newer Python).')
    node=args.node or shutil.which('node')
    if not node:fail('Node.js 24+ and npm are required. Install them from nodejs.org, then rerun setup.')
    env=environment(node)
    try:major=int(subprocess.check_output([node,'--version'],text=True).strip().lstrip('v').split('.')[0])
    except (ValueError,OSError):fail('Could not run Node.js. Check --node or PATH.')
    if major<24:fail('Node.js 24+ is required.')
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm',path=env['PATH'])
    if not npm:fail('npm was not found beside Node.js or on PATH.')
    marker=app/'.savedagain-app.json'
    if app.exists() and any(app.iterdir()) and not marker.exists():fail('Refusing to overwrite an existing unrecognized app directory. Choose another --workspace.')
    if data.exists() and data.is_symlink():fail('Choose a real directory for private library storage.')
    app.mkdir(parents=True,exist_ok=True);data.mkdir(parents=True,exist_ok=True);private(data)
    shutil.copytree(BUNDLE,app,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','.venv'))
    marker.write_text(json.dumps({'application':'savedagain','version':VERSION}))
    py=python_in(app)
    if not py.exists():subprocess.run([sys.executable,'-m','venv',str(app/'.venv')],check=True)
    subprocess.run([str(py),'-m','pip','install','-r',str(app/'backend'/'requirements.txt')],check=True)
    subprocess.run([npm,'ci'],cwd=app,env=env,check=True)
    subprocess.run([npm,'run','build'],cwd=app,env=env,check=True)
    print('Setup complete. Your library is preserved at '+str(data))

def install_analysis(args):
    app,_=paths(args);py=python_in(app)
    if not py.exists():fail('Run setup before installing optional analyzers.')
    requirements=app/'backend'/'requirements-analysis.txt'
    if not requirements.exists():fail('This installation does not include the optional analyzer manifest. Run setup to update it.')
    subprocess.run([str(py),'-m','pip','install','-r',str(requirements)],check=True)
    print('Analyzer code installed. Configure private local model paths before analysis; SavedAgain will not download model weights automatically.')

def configure_cloud(args):
    _,data=paths(args);data.mkdir(parents=True,exist_ok=True);private(data)
    if not args.url.startswith('https://'):fail('Cloud URL must use HTTPS.')
    access_secret=getpass.getpass('Cloudflare Access client secret: ')
    sync_secret=getpass.getpass('SavedAgain sync secret: ')
    if not access_secret or not sync_secret:fail('Both secrets are required. Nothing was saved.')
    config=data/'cloud.json'
    config.write_text(json.dumps({'SAVEDAGAIN_CLOUD_URL':args.url.rstrip('/'),'CF_ACCESS_CLIENT_ID':args.access_client_id,'CF_ACCESS_CLIENT_SECRET':access_secret,'SAVEDAGAIN_SYNC_SECRET':sync_secret}))
    private(config);print('Saved private cloud configuration at '+str(config))

def request(data,path,body=None,method=None,authenticate=True):
    state=read_json(data/'runtime.json')
    if not state:fail('No running instance recorded. Run start first.')
    headers={}
    if authenticate:headers['Authorization']='Bearer '+(data/'.access-key').read_text().strip()
    blob=None
    if body is not None:blob=json.dumps(body).encode();headers['Content-Type']='application/json'
    req=urllib.request.Request('http://127.0.0.1:'+str(state['port'])+path,data=blob,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)

def alive(data):
    state=read_json(data/'runtime.json')
    if not state:return False
    try:return request(data,'/api/health',authenticate=False).get('instance')==state['instance']
    except (OSError,ValueError):return False

def start(args):
    app,data=paths(args)
    if not python_in(app).exists() or not (app/'dist/client/index.html').exists():fail('Run setup before start.')
    data.mkdir(parents=True,exist_ok=True);private(data)
    if alive(data):print('Already running: http://127.0.0.1:'+str(read_json(data/'runtime.json')['port']));return
    if not 1024<=args.port<=65535:fail('Choose a port between 1024 and 65535.')
    port=None
    for candidate in range(args.port,min(args.port+11,65536)):
        with socket.socket() as probe:
            if os.name!='nt':probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:probe.bind(('127.0.0.1',candidate));port=candidate;break
            except OSError:continue
    if port is None:fail('No free port in the requested range. Choose --port.')
    instance=uuid.uuid4().hex;env=os.environ.copy();env.update(SAVEDAGAIN_DATA=str(data),SAVEDAGAIN_INSTANCE=instance)
    cloud=read_json(data/'cloud.json',{})
    if cloud:env.update({key:str(value) for key,value in cloud.items() if key in {'SAVEDAGAIN_CLOUD_URL','CF_ACCESS_CLIENT_ID','CF_ACCESS_CLIENT_SECRET','SAVEDAGAIN_SYNC_SECRET'}})
    with (data/'server.log').open('ab') as log:
        process=subprocess.Popen([str(python_in(app)),'-m','uvicorn','backend.server:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=app,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=os.name!='nt',creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
    (data/'runtime.json').write_text(json.dumps({'port':port,'pid':process.pid,'instance':instance}));private(data/'runtime.json')
    for _ in range(100):
        if alive(data):
            print('SavedAgain: http://127.0.0.1:'+str(port));print('Access key: run the key command. Private data: '+str(data));return
        if process.poll() is not None:fail('Server exited. Read '+str(data/'server.log'))
        time.sleep(.1)
    process.terminate();fail('Server did not become ready. Read '+str(data/'server.log'))

def status(args):
    _,data=paths(args)
    if not alive(data):print('SavedAgain is stopped.');return
    library=request(data,'/api/library')
    print(json.dumps({'url':'http://127.0.0.1:'+str(read_json(data/'runtime.json')['port']),'total':library['total'],'organized':library['organized'],'needs_review':library['needs_review'],'coverage':library['coverage']},indent=2))

def stop(args):
    _,data=paths(args)
    if not alive(data):print('No matching running instance. Nothing stopped.');return
    os.kill(read_json(data/'runtime.json')['pid'],signal.SIGTERM)
    for _ in range(50):
        if not alive(data):break
        time.sleep(.1)
    print('Stopped this SavedAgain instance.')

def import_batch(args):
    _,data=paths(args)
    if not args.browser_capture:fail('Imports require a supported logged-in browser capture. Use --browser-capture only for records actually observed through browser tools.')
    body=read_json(args.file)
    if not isinstance(body,dict) or not isinstance(body.get('records'),list):fail('Expected a browser-capture JSON object with a records array.')
    if len(body['records'])>25:fail('Split capture into batches of at most 25 records.')
    body.setdefault('batch_id',uuid.uuid4().hex)
    response=request(data,'/api/import',body)
    if response.get('batch_id')!=body['batch_id']:fail('Batch acknowledgement did not match. Recheck checkpoint before advancing.')
    print(json.dumps(response))

def scan_inbox(args):
    _,data=paths(args);print(json.dumps(request(data,'/api/analysis/inbox/scan',{},method='POST'),indent=2))

def sync_cloud(args):
    _,data=paths(args);print(json.dumps(request(data,'/api/sync/run',{},method='POST'),indent=2))

def backup(args):
    _,data=paths(args)
    if not (data/'library.sqlite').exists():fail('No library database exists yet.')
    out=args.output.expanduser().resolve() if args.output else data/'backups'/('savedagain-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'.tar.gz')
    if out.name in {'library.sqlite','library.sqlite-wal','library.sqlite-shm','.access-key','runtime.json','import-status.json'} and out.parent==data:fail('Backup output cannot overwrite library state.')
    if any(data/name==out or data/name in out.parents for name in ['capture','thumbnails']):fail('Backup output must be outside the captured files and previews.')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        db=Path(temporary)/'library.sqlite'
        with sqlite3.connect(data/'library.sqlite') as source,sqlite3.connect(db) as target:source.backup(target)
        with tarfile.open(out,'w:gz') as archive:
            archive.add(db,arcname='library.sqlite')
            for name in ['thumbnails','capture','analysis','.access-key','import-status.json','cloud.json']:
                if (data/name).exists():archive.add(data/name,arcname=name,filter=lambda entry:entry if entry.isfile() or entry.isdir() else None)
    private(out);print(out)

def restore(args):
    target=args.to.expanduser().resolve()
    if target.exists() and any(target.iterdir()):fail('Restore requires an empty target directory. Your existing library will not be overwritten.')
    allowed={'library.sqlite','thumbnails','capture','analysis','.access-key','import-status.json','cloud.json'}
    with tarfile.open(args.file,'r:gz') as archive:
        members=archive.getmembers()
        for entry in members:
            path=PurePosixPath(entry.name)
            if not path.parts or path.parts[0] not in allowed or path.is_absolute() or '..' in path.parts or '\\' in entry.name or not(entry.isfile() or entry.isdir()):fail('Unsafe or unexpected backup member: '+entry.name)
        target.mkdir(parents=True,exist_ok=True);private(target)
        for entry in members:
            dest=target.joinpath(*PurePosixPath(entry.name).parts)
            if entry.isdir():dest.mkdir(parents=True,exist_ok=True)
            else:
                dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(entry) as source,dest.open('wb') as output:shutil.copyfileobj(source,output)
            private(dest)
    print('Restored private library to '+str(target))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,default=Path.home()/'SavedAgain');p.add_argument('--data',type=Path)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('setup');s.add_argument('--node');s.set_defaults(run=setup)
    s=sub.add_parser('doctor');s.add_argument('--json',action='store_true');s.set_defaults(run=doctor)
    s=sub.add_parser('models');s.add_argument('--json',action='store_true');s.set_defaults(run=models_status)
    sub.add_parser('install-analysis').set_defaults(run=install_analysis)
    s=sub.add_parser('start');s.add_argument('--port',type=int,default=8765);s.set_defaults(run=start)
    sub.add_parser('status').set_defaults(run=status);sub.add_parser('stop').set_defaults(run=stop)
    sub.add_parser('key').set_defaults(run=lambda a:print((paths(a)[1]/'.access-key').read_text().strip()))
    s=sub.add_parser('import');s.add_argument('file',type=Path);s.add_argument('--browser-capture',action='store_true');s.set_defaults(run=import_batch)
    sub.add_parser('scan-inbox').set_defaults(run=scan_inbox)
    sub.add_parser('sync').set_defaults(run=sync_cloud)
    s=sub.add_parser('configure-cloud');s.add_argument('--url',required=True);s.add_argument('--access-client-id',required=True);s.set_defaults(run=configure_cloud)
    s=sub.add_parser('cloud-template');s.add_argument('--database-id',required=True);s.add_argument('--output',type=Path);s.add_argument('--force',action='store_true');s.set_defaults(run=cloud_template)
    s=sub.add_parser('backup');s.add_argument('--output',type=Path);s.set_defaults(run=backup)
    s=sub.add_parser('restore');s.add_argument('file',type=Path);s.add_argument('--to',type=Path,required=True);s.set_defaults(run=restore)
    args=p.parse_args()
    try:return args.run(args) or 0
    except (RuntimeError,OSError,ValueError,subprocess.CalledProcessError,tarfile.TarError) as error:print('SavedAgain: '+str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
