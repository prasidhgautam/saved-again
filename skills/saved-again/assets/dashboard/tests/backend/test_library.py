import os
import tempfile
import pytest
from pathlib import Path
os.environ['SAVEDAGAIN_DATA']=tempfile.mkdtemp(prefix='savedagain-test-')
from fastapi.testclient import TestClient
from backend import server
client=TestClient(server.app)
headers={'Authorization':'Bearer '+server.KEY}

@pytest.fixture(autouse=True)
def isolated_records():
    client.cookies.clear()
    with server.conn() as c:
        for table in ['analysis_artifacts','analysis_jobs','embeddings','cloud_sync','applied_mutations','sync_meta','gold_labels','memberships','posts','search','meta','sessions']:
            c.execute('DELETE FROM '+table)


def post(id='Test001',caption='A chicken fried rice recipe. Ingredients and cooking steps.'):
    return {'id':id,'url':f'https://www.instagram.com/p/{id}/','caption':caption,'order':0}
def test_authentication_and_session():
    assert client.get('/api/library').status_code==401
    assert client.post('/api/session',json={'key':'wrong'}).status_code==401
    assert client.post('/api/session',json={'key':server.KEY}).status_code==200
    assert client.get('/api/library').status_code==200
    assert client.delete('/api/session').status_code==200
    assert client.get('/api/library').status_code==401

def test_import_is_idempotent_and_preserves_edits():
    body={'records':[post()]}
    assert client.post('/api/import',json=body,headers=headers).json()['accepted']==1
    assert client.post('/api/import',json=body,headers=headers).json()['total']==1
    assert client.patch('/api/items/Test001',headers=headers,json={'notes':'Cook on Sunday','favourite':True,'tried':True,'category':'learning','subcategory':'My recipes'}).status_code==200
    client.post('/api/import',json=body,headers=headers)
    categorized={**post(),'category':'food','subcategory':'Recipes','categories':[{'category':'food','subcategory':'Recipes'}]}
    client.post('/api/import',json={'records':[categorized]},headers=headers)
    item=client.get('/api/items/Test001',headers=headers).json()
    assert item['notes']=='Cook on Sunday' and item['favourite']==1 and item['tried']==1
    assert item['category']=='learning' and item['subcategory']=='My recipes'

def test_search_categories_and_unicode():
    client.post('/api/import',headers=headers,json={'records':[post('Test002','Meta ads: test different creative concepts and hooks.'),post('Test003','Filmmaking and editing in DaVinci Resolve. कहानी')]})
    assert client.get('/api/items',headers=headers,params={'q':'DaVinci'}).json()['total']==1
    assert client.get('/api/items',headers=headers,params={'q':'कहानी'}).json()['total']==1
    assert client.get('/api/items',headers=headers,params={'category':'marketing','subcategory':'Meta ads'}).json()['total']==1
    assert client.get('/api/items',headers=headers,params={'q':'" OR * DROP TABLE posts;'}).status_code==200

def test_invalid_source_and_origin_rejected():
    p=post('Invalid001');p['url']='https://example.com/a'
    assert client.post('/api/import',headers=headers,json={'records':[p]}).json()['accepted']==0
    assert client.patch('/api/items/Test002',headers={**headers,'Origin':'https://example.com'},json={'favourite':True}).status_code==403

def test_snooze_and_reminder_exclusions():
    client.post('/api/import',headers=headers,json={'records':[post(),post('Test002','Meta ads creative test.'),post('Test003','DaVinci editing workflow.')]})
    client.patch('/api/items/Test001',headers=headers,json={'tried':True})
    client.patch('/api/items/Test002',headers=headers,json={'snoozed_until':'2099-01-01T00:00:00+00:00'})
    ids=[r['id'] for r in client.get('/api/items',params={'view':'revisit'},headers=headers).json()['items']]
    assert 'Test002' not in ids and 'Test001' not in ids
    client.patch('/api/items/Test003',headers=headers,json={'dismissed':True})
    assert client.get('/api/digest',headers=headers).json()['items']==[]

def test_backup_restores_saved_user_state():
    client.post('/api/import',headers=headers,json={'records':[post()]})
    client.patch('/api/items/Test001',headers=headers,json={'notes':'Cook on Sunday','favourite':True,'category':'learning','subcategory':'My recipes'})
    backup=client.get('/api/export',headers=headers).json()
    client.patch('/api/items/Test001',headers=headers,json={'notes':'Changed','favourite':False,'category':'food','subcategory':'Changed category'})
    assert client.post('/api/restore',headers=headers,json=backup).status_code==200
    restored=client.get('/api/items/Test001',headers=headers).json()
    assert restored['notes']=='Cook on Sunday' and restored['favourite']==1
    assert restored['category']=='learning'
    assert restored['subcategory']=='My recipes'

def test_caption_enrichment_survives_a_grid_reimport():
    original=post('Enriched001','Photo by Example on March 1, 2026.')
    client.post('/api/import',headers=headers,json={'records':[original]})
    enriched={**original,'caption':'A DaVinci editing workflow with useful keyboard shortcuts.','caption_source':'post','creator':'example','curated':True,'title':'DaVinci keyboard shortcuts'}
    response=client.post('/api/import',headers=headers,json={'records':[enriched],'batch_id':'unique-checkpoint-1'})
    assert response.json()['batch_id']=='unique-checkpoint-1'
    client.post('/api/import',headers=headers,json={'records':[original]})
    saved=client.get('/api/items/Enriched001',headers=headers).json()
    assert saved['caption']==enriched['caption'] and saved['creator']=='example'
    assert saved['title']=='DaVinci keyboard shortcuts'

def test_category_correction_updates_search_index():
    client.post('/api/import',headers=headers,json={'records':[post('Enriched001')]})
    client.patch('/api/items/Enriched001',headers=headers,json={'category':'learning','subcategory':'Personal reference shelf'})
    assert client.get('/api/items',headers=headers,params={'q':'shelf'}).json()['total']==1

def test_custom_category_rename_and_backup_roundtrip():
    assert client.get('/api/categories').status_code==401
    assert client.post('/api/categories',headers=headers,json={'id':'garden','name':'Garden'}).status_code==201
    assert client.post('/api/categories',headers=headers,json={'id':'garden','name':'Duplicate'}).status_code==409
    record={**post('Garden001','Sow seeds in spring.'),'category':'garden','subcategory':'Seeds','categories':[{'category':'garden','subcategory':'Seeds'}],'curated':True}
    assert client.post('/api/import',headers=headers,json={'records':[record]}).status_code==200
    assert client.patch('/api/categories/garden',headers=headers,json={'name':'My garden'}).status_code==200
    library=client.get('/api/library',headers=headers).json()
    category=next(c for c in library['categories'] if c['id']=='garden')
    assert category['name']=='My garden' and category['art']=='neutral.webp' and category['count']==1
    backup=client.get('/api/export',headers=headers).json()
    with server.conn() as c:
        c.execute("DELETE FROM memberships");c.execute('DELETE FROM posts');c.execute("DELETE FROM categories WHERE id='garden'")
    assert client.post('/api/restore',headers=headers,json=backup).status_code==200
    assert client.get('/api/items/Garden001',headers=headers).json()['category']=='garden'
    assert any(c['name']=='My garden' for c in client.get('/api/categories',headers=headers).json()['items'])

def test_migrate_old_category_table_without_overwriting_edits():
    client.post('/api/import',headers=headers,json={'records':[post('Old001')]})
    client.patch('/api/items/Old001',headers=headers,json={'notes':'keep this','category':'learning','subcategory':'Old shelf'})
    with server.conn() as c:c.execute('DROP TABLE categories')
    server.init();server.init()
    item=client.get('/api/items/Old001',headers=headers).json()
    assert item['notes']=='keep this' and item['category']=='learning' and item['subcategory']=='Old shelf'
    assert len(client.get('/api/categories',headers=headers).json()['items'])==len(server.CATEGORIES)

def test_reminder_history_and_custom_edits_survive_reimport():
    records=[post('Film001','DaVinci editing workflow.'),post('Food001'),post('Ad001','Meta ads creative test.')]
    client.post('/api/import',headers=headers,json={'records':records})
    digest=client.get('/api/digest',headers=headers).json()['items'];assert len(digest)==3
    client.post('/api/digest/seen',headers=headers,json={'ids':[x['id'] for x in digest]})
    assert client.get('/api/digest',headers=headers).json()['items']==[]
    snapshot=client.get('/api/export',headers=headers).json()
    with server.conn() as c:c.execute("DELETE FROM meta WHERE key='reminder_history'")
    client.post('/api/restore',headers=headers,json=snapshot)
    assert client.get('/api/digest',headers=headers).json()['items']==[]
    client.patch('/api/items/Film001',headers=headers,json={'notes':'an edit','category':'style','subcategory':'My choice'})
    client.post('/api/import',headers=headers,json={'records':records})
    item=client.get('/api/items/Film001',headers=headers).json();assert item['notes']=='an edit' and item['category']=='style'

def test_sparse_carousel_unavailable_and_rate_limit_checkpoint():
    records=[{**post('Sparse001','Photo by Example on April 1, 2026.'),'media_type':'carousel'},
             {**post('Gone001',''),'access_status':'inaccessible','inspected_at':'2026-01-01T00:00:00+00:00'}]
    body={'records':records,'batch_id':'before-interruption','coverage':{'status':'partial','browser_blocker':'HTTP 429','all_posts_end_confirmed':False}}
    assert client.post('/api/import',headers=headers,json=body).json()['batch_id']=='before-interruption'
    assert client.get('/api/items/Sparse001',headers=headers).json()['category']=='review'
    queue=client.get('/api/enrichment-queue',headers=headers).json()
    assert [x['id'] for x in queue['records']]==['Sparse001']
    checkpoint=client.get('/api/checkpoint',headers=headers).json();assert checkpoint['coverage']['status']=='partial'
    client.post('/api/import',headers=headers,json=body)
    assert client.get('/api/items',headers=headers).json()['total']==2
    assert client.get('/api/library',headers=headers).json()['inaccessible']==1

def test_invalid_categories_do_not_create_orphan_memberships():
    assert client.post('/api/categories',headers=headers,json={'id':'bad/path','name':'Bad'}).status_code==400
    assert client.post('/api/categories',headers=headers,json={'id':'nice','name':'Nice','art':'../../secret'}).status_code==400
    bad={**post('BadCategory001'),'category':'unknown','categories':[{'category':'unknown','subcategory':'X'}]}
    assert client.post('/api/import',headers=headers,json={'records':[bad]}).status_code==400
    assert client.get('/api/items',headers=headers).json()['total']==0


def test_local_capabilities_and_analysis_upload_validation():
    client.post('/api/import',headers=headers,json={'records':[post('Media001')]})
    capabilities=client.get('/api/capabilities',headers=headers).json()
    assert capabilities['mode']=='local' and capabilities['analysis'] is True and capabilities['raw_evidence'] is True
    response=client.post('/api/items/Media001/media',headers=headers,files={'file':('not-video.txt',b'synthetic','text/plain')})
    assert response.status_code==400


def test_manual_category_wins_over_high_confidence_analysis():
    client.post('/api/import',headers=headers,json={'records':[post('Manual001')]})
    client.patch('/api/items/Manual001',headers=headers,json={'category':'learning','subcategory':'My choice'})
    server.apply_analysis_result('Manual001',{'fusion':{'category':'food','score':.99,'margin':.9,'confidence':'high','auto_file':True,'alternatives':[],'evidence':['text','visual'],'explanation':'synthetic','version':'fusion-v1'},'stages':{}})
    saved=client.get('/api/items/Manual001',headers=headers).json()
    assert (saved['category'],saved['subcategory'])==('learning','My choice')
    assert saved['classification_suggestion']['category']=='food'


def test_gold_labels_metrics_and_bulk_reclassification_are_preview_only():
    client.post('/api/import',headers=headers,json={'records':[post('Gold001'),post('Gold002','Meta ads ROAS and campaign creative.')]})
    assert client.put('/api/evaluation/labels/Gold001',headers=headers,json={'category':'food','subcategory':'Recipes'}).status_code==200
    assert client.put('/api/evaluation/labels/Gold002',headers=headers,json={'category':'marketing','subcategory':'Meta ads'}).status_code==200
    metrics=client.get('/api/evaluation/metrics',headers=headers).json()
    assert metrics['labelled']==2 and metrics['accuracy']==1 and metrics['ready'] is False
    before=client.get('/api/items/Gold001',headers=headers).json()['category']
    preview=client.post('/api/reclassification/preview',headers=headers,json={'limit':10}).json()
    assert preview['preview_only'] is True
    assert client.get('/api/items/Gold001',headers=headers).json()['category']==before
