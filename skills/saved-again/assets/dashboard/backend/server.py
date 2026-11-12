from __future__ import annotations
import os, json, sqlite3, secrets, hashlib, hmac, time, re, tempfile, threading, shutil, base64, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .classify import analyze, CATEGORIES
from .analysis import (
    VIDEO_SUFFIXES, create_job, discover_topics, ensure_schema as ensure_analysis_schema, match_inbox_entry,
    process_job, retry_transcription_job,
)
from .cloud_sync import CloudSyncClient, ensure_schema as ensure_sync_schema, run_sync

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('SAVEDAGAIN_DATA',Path.home()/'SavedAgain'/'library')).resolve()
DATA.mkdir(parents=True,exist_ok=True)
DATA.chmod(0o700)
for name in ['capture','thumbnails','evidence','analysis','inbox','uploads']: (DATA/name).mkdir(exist_ok=True)
DB=DATA/'library.sqlite'
KEYFILE=DATA/'.access-key'
if not KEYFILE.exists():
    KEYFILE.write_text(secrets.token_urlsafe(32)); KEYFILE.chmod(0o600)
KEY=os.environ.get('SAVEDAGAIN_ACCESS_KEY',KEYFILE.read_text().strip())
@asynccontextmanager
async def lifespan(_app):
    start_maintenance()
    try:yield
    finally:stop_maintenance()
app=FastAPI(title='SavedAgain',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
pool=ThreadPoolExecutor(max_workers=6)
analysis_pool=ThreadPoolExecutor(max_workers=1)
thumb_pending=set(); thumb_lock=threading.Lock()
maintenance_stop=threading.Event(); maintenance_started=False; maintenance_lock=threading.Lock(); cloud_sync_lock=threading.Lock()

def now(): return datetime.now(timezone.utc).isoformat()
def conn():
    c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def init():
    with conn() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY,data TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,
          favourite INTEGER NOT NULL DEFAULT 0,tried INTEGER NOT NULL DEFAULT 0,dismissed INTEGER NOT NULL DEFAULT 0,
          snoozed_until TEXT,notes TEXT NOT NULL DEFAULT '',manual_category INTEGER NOT NULL DEFAULT 0,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memberships(post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,category TEXT,subcategory TEXT,
          UNIQUE(post_id,category,subcategory));
        CREATE INDEX IF NOT EXISTS membership_category ON memberships(category,subcategory);
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED,body,tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY,name TEXT NOT NULL,art TEXT NOT NULL,color TEXT NOT NULL,rank INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,expires INTEGER);
        CREATE TABLE IF NOT EXISTS gold_labels(post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,category TEXT NOT NULL,subcategory TEXT,labelled_at TEXT NOT NULL);
        ''')
        columns={row['name'] for row in c.execute('PRAGMA table_info(posts)')}
        if 'revision' not in columns:c.execute('ALTER TABLE posts ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
        ensure_analysis_schema(c);ensure_sync_schema(c)
        for rank,(slug,(name,art,color)) in enumerate(CATEGORIES.items()):
            c.execute('INSERT OR IGNORE INTO categories VALUES(?,?,?,?,?)',(slug,name,art,color,rank))
init()

def category_rows():
    with conn() as c:return [dict(r) for r in c.execute('SELECT * FROM categories ORDER BY rank,id')]

def meta(key,default=None):
    with conn() as c:r=c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(r[0]) if r else default
def setmeta(c,key,val): c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(val)))
def authorized(request):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    if token and hmac.compare_digest(token,KEY):return True
    sid=request.cookies.get('savedagain_session','')
    if not sid:return False
    with conn() as c:r=c.execute('SELECT expires FROM sessions WHERE id=?',(hashlib.sha256(sid.encode()).hexdigest(),)).fetchone()
    return bool(r and r[0]>time.time())
@app.middleware('http')
async def guard(request,call_next):
    if request.url.path.startswith(('/api/','/media/')) and request.url.path not in ('/api/session','/api/health'):
        if not authorized(request): return JSONResponse({'detail':'Please unlock your library.'},status_code=401)
        if request.method not in ('GET','HEAD'):
            origin=request.headers.get('origin')
            if origin and origin!=f'{request.url.scheme}://{request.headers.get("host")}':
                return JSONResponse({'detail':'Origin not allowed'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    if request.url.path.startswith(('/api/','/media/')):response.headers['Cache-Control']='no-store'
    return response

class Login(BaseModel):key:str
@app.post('/api/session')
def login(body:Login,request:Request):
    if not hmac.compare_digest(body.key,KEY):raise HTTPException(401,'That access key did not match.')
    sid=secrets.token_urlsafe(40)
    with conn() as c:c.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(sid.encode()).hexdigest(),int(time.time()+86400*30)))
    r=JSONResponse({'ok':True});r.set_cookie('savedagain_session',sid,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=86400*30);return r
@app.delete('/api/session')
def logout(request:Request):
    sid=request.cookies.get('savedagain_session','')
    with conn() as c:c.execute('DELETE FROM sessions WHERE id=?',(hashlib.sha256(sid.encode()).hexdigest(),))
    r=JSONResponse({'ok':True});r.delete_cookie('savedagain_session');return r

def download_thumb(id,url):
    try:
        host=urlparse(url).hostname or ''
        if not (host.endswith('.fbcdn.net') or host.endswith('.cdninstagram.com') or host=='i.pinimg.com'):return
        path=DATA/'thumbnails'/f'{id}.jpg'
        if path.exists():return
        with httpx.Client(timeout=25,follow_redirects=False) as client:
            r=client.get(url,headers={'User-Agent':'Mozilla/5.0'})
        if r.status_code==200 and r.headers.get('content-type','').startswith('image/') and len(r.content)<12_000_000:
            tmp=path.with_suffix('.tmp');tmp.write_bytes(r.content);tmp.replace(path)
    except Exception:pass
    finally:
        with thumb_lock:thumb_pending.discard(id)
def schedule_thumb(id,url):
    if not url or (DATA/'thumbnails'/f'{id}.jpg').exists():return
    with thumb_lock:
        if id in thumb_pending:return
        thumb_pending.add(id)
    pool.submit(download_thumb,id,url)

def upsert(records,coverage=None,restoring=False):
    good=0
    with conn() as c:
        for raw in records:
            id=raw.get('id','')
            if not re.fullmatch(r'[\w-]{3,120}',id,re.ASCII):continue
            url=raw.get('url','')
            if not re.fullmatch(r'https://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reel)/'+re.escape(id)+r'/?',url):continue
            old=c.execute('SELECT * FROM posts WHERE id=?',(id,)).fetchone()
            data=json.loads(old['data']) if old and not restoring else {}
            incoming={k:v for k,v in raw.items() if k not in ('notes','favourite','tried','dismissed','snoozed_until')}
            if data.get('caption_source')=='post' and raw.get('caption_source')!='post':
                for k in ['caption','caption_source','creator','access_status','inspected_at']:
                    if k in data:incoming[k]=data[k]
            label=raw.get('media_label','').lower()
            if 'media_type' not in incoming:incoming['media_type']='carousel' if 'carousel' in label else 'reel' if 'clip' in label else 'video' if label=='video' else 'post'
            elif not restoring and incoming['media_type']=='post' and label=='video':incoming['media_type']='video'
            merged={**data,**incoming}
            computed=analyze(merged)
            # Preserve explicitly curated text during future capture-only imports.
            for k in ['title','summary','use_when','tags','categories','category','subcategory','evidence']:
                if k in raw:computed[k]=raw[k]
                elif data.get('curated') and k in data:computed[k]=data[k]
            if old and old['manual_category'] and not restoring:
                for k in ['category','subcategory','categories']:computed[k]=data[k]
                computed['organization_status']='needs_review' if data['category']=='review' else 'organized'
            computed['organization_status']='needs_review' if computed['category']=='review' else 'organized'
            known={r['id'] for r in category_rows()}
            if computed['category'] not in known or any(pair['category'] not in known for pair in computed['categories']):
                raise HTTPException(400,'Create the category before importing records assigned to it.')
            merged.update(computed)
            if old:
                merged['collections']=list(dict.fromkeys(data.get('collections',[])+raw.get('collections',[])))
            c.execute('INSERT INTO posts(id,data,position,updated) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,position=excluded.position,updated=excluded.updated,revision=posts.revision+1',
                (id,json.dumps(merged,ensure_ascii=False),raw.get('order',old['position'] if old else good),now()))
            c.execute('DELETE FROM memberships WHERE post_id=?',(id,))
            for pair in merged['categories']:c.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)',(id,pair['category'],pair['subcategory']))
            c.execute('DELETE FROM search WHERE id=?',(id,))
            c.execute('INSERT INTO search VALUES(?,?)',(id,' '.join(str(merged.get(k,'')) for k in ['title','summary','caption','tags','creator','subcategory','use_when'])))
            schedule_thumb(id,merged.get('thumbnail_url',''));good+=1
        if coverage:
            oldcoverage=meta('coverage',{})
            setmeta(c,'coverage',{**oldcoverage,**coverage,'updated':now()})
    return good

class Batch(BaseModel):
    records:list[dict]
    coverage:dict|None=None
    evidence:dict|None=None
    batch_id:str|None=None
@app.post('/api/import')
def import_batch(body:Batch):
    if len(body.records)>25:raise HTTPException(400,'Import at most 25 records per batch.')
    if body.evidence:
        name=body.evidence.get('name','')
        if not re.fullmatch(r'[a-z0-9-]+\.jpg',name):raise HTTPException(400,'Invalid evidence filename')
        try:blob=base64.b64decode(body.evidence.get('base64',''),validate=True)
        except Exception:raise HTTPException(400,'Invalid screenshot')
        if len(blob)>8_000_000 or not blob.startswith(b'\xff\xd8'):raise HTTPException(400,'Invalid screenshot')
        (DATA/'evidence'/name).write_bytes(blob)
    stamp=str(time.time_ns());path=DATA/'capture'/f'batch-{stamp}.json'
    path.write_text(body.model_dump_json(),encoding='utf-8')
    count=upsert(body.records,body.coverage)
    return {'accepted':count,'total':count_posts(),'batch_id':body.batch_id}
def count_posts():
    with conn() as c:return c.execute('SELECT count(*) FROM posts').fetchone()[0]
@app.get('/api/checkpoint')
def checkpoint():
    with conn() as c:rows=c.execute('SELECT id,position FROM posts ORDER BY position').fetchall()
    return {'coverage':meta('coverage',{}),'categories':category_rows(),'reminder_history':meta('reminder_history',{}),'records':[dict(r) for r in rows]}
@app.get('/api/enrichment-queue')
def enrichment_queue(kind:str='captions'):
    with conn() as c:rows=c.execute('SELECT data FROM posts ORDER BY position').fetchall()
    records=[json.loads(r[0]) for r in rows]
    queue=([r for r in records if not r.get('thumbnail_url')] if kind=='previews' else
           [r for r in records if not r.get('inspected_at') and (not r.get('caption') or re.match(r'^(photo by |photo shared by |this may contain|this contains)',r.get('caption',''),re.I))])
    return {'remaining':len(queue),'records':queue}

def analysis_labels():
    labels={row['id']:row['name'] for row in category_rows() if row['id']!='review'}
    with conn() as c:groups=c.execute('SELECT category,group_concat(DISTINCT subcategory) topics FROM memberships GROUP BY category').fetchall()
    for row in groups:
        if row['category'] in labels and row['topics']:labels[row['category']]+=': '+row['topics']
    return labels

def exemplar_category_scores(modality,vector):
    scores={}
    with conn() as c:
        rows=c.execute('SELECT p.data,e.vector FROM embeddings e JOIN posts p ON p.id=e.post_id WHERE e.modality=? AND p.manual_category=1',(modality,)).fetchall()
    for row in rows:
        exemplar=json.loads(row['vector']);category=json.loads(row['data']).get('category')
        if not category or len(exemplar)!=len(vector):continue
        similarity=max(0.0,min(1.0,(sum(a*b for a,b in zip(vector,exemplar))+1.0)/2.0))
        scores[category]=max(scores.get(category,0),similarity)
    return scores

def apply_analysis_result(post_id,result):
    with conn() as c:
        row=c.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
        if not row:return
        data=json.loads(row['data']);previous=data.get('analysis',{})
        data['analysis']={**previous,**result}
        fusion=result.get('fusion')
        if fusion:
            data['classification_suggestion']=fusion
            if fusion.get('auto_file') and not row['manual_category'] and fusion.get('category') in {r['id'] for r in category_rows()}:
                previous_category=data.get('category');data['category']=fusion['category'];data['subcategory']=data.get('subcategory') if previous_category==fusion['category'] else 'General'
                data['categories']=[{'category':data['category'],'subcategory':data['subcategory']}]
                data['organization_status']='organized'
                c.execute('DELETE FROM memberships WHERE post_id=?',(post_id,))
                c.execute('INSERT INTO memberships VALUES(?,?,?)',(post_id,data['category'],data['subcategory']))
        summary=result.get('summary') or {}
        if summary:data['analysis_summary']=summary
        c.execute('UPDATE posts SET data=?,updated=?,revision=revision+1 WHERE id=?',(json.dumps(data,ensure_ascii=False),now(),post_id))
        c.execute('DELETE FROM search WHERE id=?',(post_id,))
        c.execute('INSERT INTO search VALUES(?,?)',(post_id,' '.join(str(data.get(k,'')) for k in ['title','summary','caption','tags','creator','subcategory','use_when'])))

def schedule_analysis(job_id):
    analysis_pool.submit(process_job,job_id,connection_factory=conn,data_dir=DATA,category_labels=analysis_labels,apply_result=apply_analysis_result,exemplar_scores=exemplar_category_scores)

def job_dict(row,artifacts=False):
    result=dict(row);result['stages']=json.loads(result.get('stages') or '{}')
    if artifacts:
        with conn() as c:
            result['artifacts']=[{**dict(item),'content':json.loads(item['content'])} for item in c.execute('SELECT * FROM analysis_artifacts WHERE job_id=? ORDER BY id',(row['id'],))]
    return result

def scan_inbox():
    queued=[];inbox=DATA/'inbox'
    with conn() as c:known_ids={row['id'] for row in c.execute('SELECT id FROM posts')}
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:continue
        post_id=match_inbox_entry(path,known_ids)
        if not post_id:continue
        with conn() as c:
            if not c.execute('SELECT 1 FROM posts WHERE id=?',(post_id,)).fetchone():continue
            existing=c.execute("SELECT 1 FROM analysis_jobs WHERE source_path=? AND status IN('queued','running','complete','waiting_for_transcription')",(str(path),)).fetchone()
            if existing:continue
            job_id=create_job(c,post_id,path,'inbox')
        schedule_analysis(job_id);queued.append({'job_id':job_id,'post_id':post_id,'source':path.name})
    return queued

@app.get('/api/capabilities')
def capabilities():
    cloud=CloudSyncClient()
    return {'mode':'local','analysis':True,'media_upload':True,'inbox':str(DATA/'inbox'),'sync':cloud.configured,'raw_evidence':True,'voice_studio':os.environ.get('SAVEDAGAIN_VOICESTUDIO_URL','http://localhost:3900')}

@app.post('/api/items/{id}/media',status_code=202)
async def attach_media(id:str,file:UploadFile=File(...)):
    with conn() as c:
        if not c.execute('SELECT 1 FROM posts WHERE id=?',(id,)).fetchone():raise HTTPException(404,'Post not found')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in VIDEO_SUFFIXES:raise HTTPException(400,'Attach an MP4, MOV, M4V, WebM, or MKV video.')
    destination=DATA/'uploads'/f'{uuid.uuid4().hex}{suffix}';size=0
    try:
        with destination.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>2_500_000_000:raise HTTPException(413,'Video exceeds the 2.5 GB local limit.')
                output.write(chunk)
        with conn() as c:job_id=create_job(c,id,destination,'manual')
        schedule_analysis(job_id)
        return {'job_id':job_id,'status':'queued'}
    except Exception:
        destination.unlink(missing_ok=True);raise
    finally:await file.close()

@app.post('/api/analysis/inbox/scan')
def scan_analysis_inbox():return {'queued':scan_inbox()}

@app.get('/api/analysis/jobs')
def analysis_jobs(post_id:str=''):
    with conn() as c:
        rows=c.execute('SELECT * FROM analysis_jobs'+(' WHERE post_id=?' if post_id else '')+' ORDER BY updated DESC LIMIT 100',(post_id,) if post_id else ()).fetchall()
    return {'items':[job_dict(row) for row in rows]}

@app.get('/api/analysis/jobs/{job_id}')
def analysis_job(job_id:str):
    with conn() as c:row=c.execute('SELECT * FROM analysis_jobs WHERE id=?',(job_id,)).fetchone()
    if not row:raise HTTPException(404,'Analysis job not found')
    return job_dict(row,artifacts=True)

@app.post('/api/analysis/jobs/{job_id}/retry',status_code=202)
def retry_analysis(job_id:str):
    with conn() as c:row=c.execute('SELECT * FROM analysis_jobs WHERE id=?',(job_id,)).fetchone()
    if not row:raise HTTPException(404,'Analysis job not found')
    if row['status']=='waiting_for_transcription':analysis_pool.submit(retry_transcription_job,job_id,connection_factory=conn,apply_result=apply_analysis_result)
    elif Path(row['source_path']).exists():schedule_analysis(job_id)
    else:raise HTTPException(409,'The source is no longer available. Attach the reel again.')
    return {'job_id':job_id,'status':'queued'}

@app.post('/api/analysis/topics')
def topic_discovery():
    with conn() as c:
        rows=c.execute("SELECT p.id,p.data,e.vector FROM posts p JOIN embeddings e ON e.post_id=p.id AND e.modality='caption' WHERE json_extract(p.data,'$.category')='review' ORDER BY p.position").fetchall()
    proposals=discover_topics([json.loads(row['vector']) for row in rows],[json.loads(row['data']).get('caption','') for row in rows])
    return {'proposals':[{**proposal,'post_id':rows[proposal['item']]['id']} for proposal in proposals]}

@app.get('/api/evaluation/sample')
def evaluation_sample(size:int=200):
    size=max(1,min(size,500))
    with conn() as c:
        rows=c.execute('SELECT p.* FROM posts p LEFT JOIN gold_labels g ON g.post_id=p.id WHERE g.post_id IS NULL ORDER BY p.position').fetchall()
    groups={}
    for row in rows:groups.setdefault(json.loads(row['data']).get('category','review'),[]).append(row)
    chosen=[]
    while len(chosen)<size and any(groups.values()):
        for category in sorted(groups):
            if groups[category] and len(chosen)<size:chosen.append(groups[category].pop(0))
    return {'items':[public_item(row) for row in chosen],'requested':size,'remaining_unlabelled':len(rows)}

@app.put('/api/evaluation/labels/{post_id}')
def label_evaluation(post_id:str,body:dict):
    category=str(body.get('category') or '')
    if category not in {row['id'] for row in category_rows()}:raise HTTPException(400,'Unknown category')
    with conn() as c:
        if not c.execute('SELECT 1 FROM posts WHERE id=?',(post_id,)).fetchone():raise HTTPException(404,'Post not found')
        c.execute('INSERT OR REPLACE INTO gold_labels VALUES(?,?,?,?)',(post_id,category,str(body.get('subcategory') or '')[:120],now()))
    return {'post_id':post_id,'category':category}

@app.get('/api/evaluation/metrics')
def evaluation_metrics():
    with conn() as c:rows=c.execute('SELECT p.data,g.category truth FROM gold_labels g JOIN posts p ON p.id=g.post_id').fetchall()
    labels=[]
    for row in rows:
        data=json.loads(row['data']);suggestion=data.get('classification_suggestion') or {}
        predicted=suggestion.get('category') or analyze(data).get('category','review')
        confidence=suggestion.get('confidence') or data.get('classification_confidence','low')
        labels.append((row['truth'],predicted,confidence))
    classes=sorted({value for truth,predicted,_ in labels for value in (truth,predicted)})
    f1=[]
    for category in classes:
        tp=sum(truth==predicted==category for truth,predicted,_ in labels)
        fp=sum(predicted==category and truth!=category for truth,predicted,_ in labels)
        fn=sum(truth==category and predicted!=category for truth,predicted,_ in labels)
        precision=tp/(tp+fp) if tp+fp else 0;recall=tp/(tp+fn) if tp+fn else 0
        f1.append(2*precision*recall/(precision+recall) if precision+recall else 0)
    total=len(labels);correct=sum(truth==predicted for truth,predicted,_ in labels)
    high=[(truth,predicted) for truth,predicted,confidence in labels if confidence=='high']
    result={'labelled':total,'accuracy':correct/total if total else 0,'macro_f1':sum(f1)/len(f1) if f1 else 0,
            'high_confidence_error':sum(truth!=predicted for truth,predicted in high)/len(high) if high else 0,'high_confidence_count':len(high)}
    result['ready']=total>=200 and result['accuracy']>=.85 and result['macro_f1']>=.75 and result['high_confidence_error']<=.05
    return result

@app.post('/api/reclassification/preview')
def reclassification_preview(body:dict=None):
    limit=max(1,min(int((body or {}).get('limit',500)),5000));changes=[]
    with conn() as c:rows=c.execute('SELECT * FROM posts ORDER BY position LIMIT ?',(limit,)).fetchall()
    for row in rows:
        data=json.loads(row['data']);proposed=analyze(data)
        if proposed['category']!=data.get('category') or proposed['subcategory']!=data.get('subcategory'):
            changes.append({'id':row['id'],'current':{'category':data.get('category'),'subcategory':data.get('subcategory')},
                            'proposed':{'category':proposed['category'],'subcategory':proposed['subcategory'],'confidence':proposed['classification_confidence']},
                            'manual_category':bool(row['manual_category'])})
    return {'preview_only':True,'examined':len(rows),'changes':changes,'change_count':len(changes),'evaluation':evaluation_metrics()}

def public_item(row):
    d=json.loads(row['data']);d.update({k:row[k] for k in ['favourite','tried','dismissed','snoozed_until','notes']})
    d['manual_category']=row['manual_category'];d['revision']=row['revision']
    d['thumbnail']=f'/media/{d["id"]}.jpg' if (DATA/'thumbnails'/f'{d["id"]}.jpg').exists() else d.get('thumbnail_url','')
    return d

def conditions(category='',subcategory='',q='',view='library'):
    where=['1'];args=[]
    if category:where.append('EXISTS(SELECT 1 FROM memberships m WHERE m.post_id=p.id AND m.category=?)');args.append(category)
    if subcategory:where.append('EXISTS(SELECT 1 FROM memberships m WHERE m.post_id=p.id AND m.category=? AND m.subcategory=?)');args.extend([category,subcategory])
    if q.strip():
        words=re.findall(r'\w+',q,re.UNICODE)[:16]
        if words:where.append('p.id IN(SELECT id FROM search WHERE search MATCH ?)');args.append(' OR '.join('"'+w+'"' for w in words))
    if view=='favourites':where.append('p.favourite=1')
    elif view=='tried':where.append('p.tried=1')
    elif view=='revisit':where.extend(['p.tried=0','p.dismissed=0',"(p.snoozed_until IS NULL OR p.snoozed_until<=?)"]);args.append(now())
    return ' AND '.join(where),args
@app.get('/api/items')
def items(category:str='',subcategory:str='',q:str='',view:str='library',page:int=1,size:int=24):
    size=max(1,min(size,100));page=max(1,page);where,args=conditions(category,subcategory,q,view)
    order='p.favourite DESC,p.position ASC' if view=='revisit' else 'p.position ASC'
    with conn() as c:
        total=c.execute('SELECT count(*) FROM posts p WHERE '+where,args).fetchone()[0]
        rows=c.execute('SELECT p.* FROM posts p WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[size,(page-1)*size]).fetchall()
    return {'items':[public_item(r) for r in rows],'total':total,'page':page,'pages':max(1,(total+size-1)//size)}
@app.get('/api/items/{id}')
def item(id:str):
    with conn() as c:r=c.execute('SELECT * FROM posts WHERE id=?',(id,)).fetchone()
    if not r:raise HTTPException(404,'Post not found')
    return public_item(r)
@app.patch('/api/items/{id}')
def update_item(id:str,body:dict):
    with conn() as c:
        row=c.execute('SELECT * FROM posts WHERE id=?',(id,)).fetchone()
        if not row:raise HTTPException(404,'Post not found')
        for key in ['favourite','tried','dismissed','snoozed_until','notes']:
            if key in body:
                val=body[key]
                if key in ['favourite','tried','dismissed']:val=int(bool(val))
                if key=='notes':val=str(val)[:20000]
                if key=='snoozed_until' and val:
                    try:datetime.fromisoformat(val)
                    except ValueError:raise HTTPException(400,'Invalid reminder date')
                c.execute(f'UPDATE posts SET {key}=? WHERE id=?',(val,id))
        if 'category' in body:
            if body['category'] not in {r['id'] for r in category_rows()}:raise HTTPException(400,'Unknown category')
            data=json.loads(row['data']);data.update(category=body['category'],subcategory=str(body.get('subcategory') or 'General')[:120])
            data['categories']=[{'category':data['category'],'subcategory':data['subcategory']}]
            data['organization_status']='needs_review' if data['category']=='review' else 'organized'
            c.execute('UPDATE posts SET data=?,manual_category=1 WHERE id=?',(json.dumps(data,ensure_ascii=False),id))
            c.execute('DELETE FROM memberships WHERE post_id=?',(id,));c.execute('INSERT INTO memberships VALUES(?,?,?)',(id,data['category'],data['subcategory']))
            c.execute('DELETE FROM search WHERE id=?',(id,))
            c.execute('INSERT INTO search VALUES(?,?)',(id,' '.join(str(data.get(k,'')) for k in ['title','summary','caption','tags','creator','subcategory','use_when'])))
        c.execute('UPDATE posts SET updated=?,revision=revision+1 WHERE id=?',(now(),id))
    return item(id)

@app.get('/api/health')
def health():
    return {'application':'savedagain','version':'1.1.0','instance':os.environ.get('SAVEDAGAIN_INSTANCE','standalone')}

def apply_remote_mutation(mutation):
    post_id=str(mutation.get('post_id') or '');patch=mutation.get('patch') or {}
    allowed={key:patch[key] for key in ['favourite','tried','dismissed','snoozed_until','notes','category','subcategory'] if key in patch}
    if not post_id or not allowed:return
    with conn() as c:
        row=c.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
        if not row:return
        for key in ['favourite','tried','dismissed','snoozed_until','notes']:
            if key in allowed:
                value=allowed[key]
                if key in ['favourite','tried','dismissed']:value=int(bool(value))
                if key=='notes':value=str(value)[:20000]
                c.execute(f'UPDATE posts SET {key}=? WHERE id=?',(value,post_id))
        if 'category' in allowed and allowed['category'] in {category['id'] for category in category_rows()}:
            data=json.loads(row['data']);data['category']=allowed['category'];data['subcategory']=str(allowed.get('subcategory') or 'General')[:120]
            data['categories']=[{'category':data['category'],'subcategory':data['subcategory']}]
            data['organization_status']='needs_review' if data['category']=='review' else 'organized'
            c.execute('UPDATE posts SET data=?,manual_category=1 WHERE id=?',(json.dumps(data,ensure_ascii=False),post_id))
            c.execute('DELETE FROM memberships WHERE post_id=?',(post_id,));c.execute('INSERT INTO memberships VALUES(?,?,?)',(post_id,data['category'],data['subcategory']))
        c.execute('UPDATE posts SET updated=?,revision=revision+1 WHERE id=?',(now(),post_id))

def cloud_sync_once():
    if not cloud_sync_lock.acquire(blocking=False):return {'configured':True,'status':'running','message':'A cloud sync is already running.'}
    try:
        try:
            result=run_sync(conn,DATA,apply_remote_mutation)
            with conn() as c:setmeta(c,'cloud_sync_status',result)
            return result
        except Exception as error:
            result={'configured':CloudSyncClient().configured,'status':'failed','message':str(error)[:1000],'updated':now()}
            with conn() as c:setmeta(c,'cloud_sync_status',result)
            return result
    finally:cloud_sync_lock.release()

@app.get('/api/sync/status')
def sync_status():return meta('cloud_sync_status',{'configured':CloudSyncClient().configured,'status':'not_started'})

@app.post('/api/sync/run')
def sync_run():return cloud_sync_once()

def maintenance_loop():
    last_sync=0.0
    while not maintenance_stop.wait(60):
        try:scan_inbox()
        except Exception:pass
        if CloudSyncClient().configured and time.time()-last_sync>=900:
            cloud_sync_once();last_sync=time.time()

def start_maintenance():
    global maintenance_started
    with maintenance_lock:
        if maintenance_started:return
        maintenance_stop.clear()
        maintenance_started=True
        threading.Thread(target=maintenance_loop,name='savedagain-maintenance',daemon=True).start()

def stop_maintenance():
    global maintenance_started
    maintenance_stop.set();maintenance_started=False

def category_values(body):
    slug=body.get('id','');name=str(body.get('name','')).strip()
    art=body.get('art','neutral.webp');color=body.get('color','#164b35')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) or len(slug)>64:raise HTTPException(400,'Use a lowercase category ID with hyphens.')
    if not name or len(name)>80:raise HTTPException(400,'Category name must be 1–80 characters.')
    if art not in {v[1] for v in CATEGORIES.values()}|{'neutral.webp'}:raise HTTPException(400,'Unknown category artwork.')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise HTTPException(400,'Use a six-digit hex color.')
    return slug,name,art,color

@app.get('/api/categories')
def categories():return {'items':category_rows()}

@app.post('/api/categories',status_code=201)
def create_category(body:dict):
    values=category_values(body)
    with conn() as c:
        try:c.execute('INSERT INTO categories VALUES(?,?,?,?,?)',(*values,100))
        except sqlite3.IntegrityError:raise HTTPException(409,'That category ID already exists.')
    return next(r for r in category_rows() if r['id']==values[0])

@app.patch('/api/categories/{slug}')
def edit_category(slug:str,body:dict):
    old=next((r for r in category_rows() if r['id']==slug),None)
    if not old:raise HTTPException(404,'Category not found')
    values=category_values({**old,**body,'id':slug})
    with conn() as c:c.execute('UPDATE categories SET name=?,art=?,color=? WHERE id=?',(*values[1:],slug))
    return next(r for r in category_rows() if r['id']==slug)

@app.get('/api/library')
def library():
    with conn() as c:
        groups=c.execute('SELECT category,subcategory,count(DISTINCT post_id) n FROM memberships GROUP BY category,subcategory').fetchall()
        status=c.execute('SELECT count(*) total,sum(favourite) favourites,sum(tried) tried FROM posts').fetchone()
        cats=[]
        for category in category_rows():
            slug,name,art,color=(category[k] for k in ['id','name','art','color'])
            sub=[{'name':r['subcategory'],'count':r['n']} for r in groups if r['category']==slug]
            preferred={'filmmaking':['Writing','Editing','Video generation','Sound','Cinematography','Image generation','Acting & casting'],
                       'marketing':['Meta ads','Hooks & copy','Creative strategy'],'food':['Recipes','High protein']}.get(slug,[])
            sub.sort(key=lambda s:(preferred.index(s['name']) if s['name'] in preferred else len(preferred),s['name']))
            if not sub:continue
            total=c.execute('SELECT count(DISTINCT post_id) FROM memberships WHERE category=?',(slug,)).fetchone()[0]
            previews=c.execute("SELECT * FROM posts WHERE json_extract(data,'$.category')=? ORDER BY position LIMIT 2",(slug,)).fetchall()
            cats.append({'id':slug,'name':name,'art':art,'color':color,'count':total,'subcategories':sub,'preview':[public_item(r) for r in previews] or items(category=slug,size=2)['items']})
        local=c.execute('SELECT id,data FROM posts').fetchall()
        records=[json.loads(r['data']) for r in local]
    thumb_count=sum((DATA/'thumbnails'/f'{r[0]}.jpg').exists() for r in local)
    return {'category_options':category_rows(),'organized':sum(r.get('category')!='review' for r in records),'needs_review':sum(r.get('category')=='review' for r in records),'account':meta('coverage',{}).get('account','your_saved_library'),'total':status['total'],'favourites':status['favourites'] or 0,'tried':status['tried'] or 0,
      'categories':cats,'coverage':meta('coverage',{'status':'not_started'}),'local_thumbnails':thumb_count,'thumbnail_pending':len(thumb_pending),
      'incomplete':sum(r.get('evidence')!='caption' or r.get('access_status')=='caption_unavailable' for r in records),
      'inaccessible':sum(r.get('access_status')=='inaccessible' for r in records)}
@app.get('/api/digest')
def digest():
    where,args=conditions(view='revisit')
    with conn() as c:rows=c.execute('SELECT p.* FROM posts p WHERE '+where,args).fetchall()
    pool_items=[public_item(r) for r in rows];chosen=[];seen=set()
    history=meta('reminder_history',{})
    priority={'filmmaking':0,'marketing':1,'food':2,'technology':3,'learning':4,'places':5,'career':6,'wellbeing':7,'style':8,'entertainment':9,'review':10}
    for d in sorted(pool_items,key=lambda d:(not d['favourite'],priority.get(d['category'],8),d.get('order',0))):
        if d.get('evidence')!='caption' or d.get('category')=='review' or d.get('access_status')=='inaccessible':continue
        last=history.get(d['id'],0)
        if time.time()-last<28*86400 or d['category'] in seen:continue
        chosen.append(d);seen.add(d['category'])
        if len(chosen)==3:break
    return {'items':chosen}
@app.post('/api/digest/seen')
def digest_seen(body:dict):
    history=meta('reminder_history',{})
    for id in body.get('ids',[])[:3]:history[id]=time.time()
    with conn() as c:setmeta(c,'reminder_history',history)
    return {'ok':True}
@app.get('/api/export')
def export():
    with conn() as c:rows=c.execute('SELECT * FROM posts ORDER BY position').fetchall()
    return JSONResponse({'version':1,'exported':now(),'coverage':meta('coverage',{}),'categories':category_rows(),'reminder_history':meta('reminder_history',{}),'records':[dict(r) for r in rows]},headers={'Content-Disposition':'attachment; filename="savedagain-backup.json"'})
@app.post('/api/restore')
def restore(body:dict):
    if body.get('version')!=1:raise HTTPException(400,'Unsupported backup version')
    with conn() as c:
        for category in body.get('categories',[]):
            valid=category_values(category)
            c.execute('INSERT OR REPLACE INTO categories VALUES(?,?,?,?,?)',(*valid,category.get('rank',100)))
        if 'reminder_history' in body:setmeta(c,'reminder_history',body['reminder_history'])
    records=[]
    for row in body.get('records',[]):
        data=json.loads(row['data']) if isinstance(row.get('data'),str) else row.get('data',{})
        records.append(data)
    upsert(records,body.get('coverage'),restoring=True)
    with conn() as c:
        for row in body.get('records',[]):
            for key in ['favourite','tried','dismissed','snoozed_until','notes','manual_category']:
                if key in row:c.execute(f'UPDATE posts SET {key}=? WHERE id=?',(row[key],row['id']))
    return {'total':count_posts()}
@app.get('/media/{name}')
def media(name:str):
    if not re.fullmatch(r'[\w-]+\.jpg',name,re.ASCII):raise HTTPException(404)
    path=DATA/'thumbnails'/name
    if not path.exists():raise HTTPException(404)
    return FileResponse(path)
@app.get('/import',response_class=HTMLResponse)
def importer():
    return '''<!doctype html><meta name="viewport" content="width=device-width"><title>SavedAgain import</title><style>body{font:16px system-ui;background:#faf4e4;color:#202719;max-width:850px;margin:50px auto;padding:20px}textarea,input{display:block;width:100%;padding:12px;box-sizing:border-box}textarea{height:350px}button{background:#e2ad16;padding:12px;border:1px solid #222;border-radius:6px;cursor:pointer}pre{white-space:pre-wrap}</style><h1>Import your saved posts</h1><p>This private import screen receives a capture from your browser.</p><label>Access key<input id="key" type="password" autocomplete="off"></label><button id="unlock">Unlock</button><label>Captured records<textarea id="records" spellcheck="false"></textarea></label><button id="import">Import batch</button><pre role="status" id="status"></pre><a href="/">Open library</a><script>const status=document.querySelector('#status');document.querySelector('#unlock').onclick=async()=>{let r=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:document.querySelector('#key').value})});status.textContent=r.ok?'Unlocked':await r.text();document.querySelector('#key').value=''};document.querySelector('#import').onclick=async()=>{try{let body=JSON.parse(document.querySelector('#records').value);status.textContent='Saving batch…';let r=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=await r.text()}catch(e){status.textContent=e.message}};</script>'''

if (ROOT/'dist/client/assets').exists():
    app.mount('/assets',StaticFiles(directory=ROOT/'dist/client/assets'),name='assets')
    app.mount('/art',StaticFiles(directory=ROOT/'dist/client/art'),name='art')
@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith(('api/','media/')):raise HTTPException(404,'Not found')
    index=ROOT/'dist/client/index.html'
    if index.exists():return FileResponse(index)
    return HTMLResponse('Frontend is being built. Import is available at <a href="/import">/import</a>.')
