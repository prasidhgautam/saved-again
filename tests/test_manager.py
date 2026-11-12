import importlib.util,sqlite3,json,tarfile,io,hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('manager',ROOT/'skills/saved-again/scripts/savedagain.py');manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)

def args(tmp_path,**extras):return SimpleNamespace(workspace=tmp_path/'workspace with spaces',data=None,**extras)

def test_portable_paths_and_non_nested_library(tmp_path):
    a=args(tmp_path);app,data=manager.paths(a)
    assert app.name=='app' and data.name=='library' and app.parent==data.parent
    a.data=app/'private'
    with pytest.raises(RuntimeError,match='separate'):manager.paths(a)

def test_missing_node_does_not_create_workspace(tmp_path,monkeypatch):
    a=args(tmp_path,node=None);monkeypatch.setattr(manager.shutil,'which',lambda *a,**k:None)
    with pytest.raises(RuntimeError,match='Node.js'):manager.setup(a)
    assert not a.workspace.exists()

def test_reject_old_node_before_modifying_workspace(tmp_path,monkeypatch):
    a=args(tmp_path,node='node');monkeypatch.setattr(manager.subprocess,'check_output',lambda *a,**k:'v18.0.0')
    with pytest.raises(RuntimeError,match='24'):manager.setup(a)
    assert not a.workspace.exists()

def test_browser_required_import_gate(tmp_path):
    a=args(tmp_path,browser_capture=False,file=tmp_path/'absent.json')
    with pytest.raises(RuntimeError,match='browser'):manager.import_batch(a)

def test_batch_limit_and_exact_acknowledgement(tmp_path,monkeypatch):
    path=tmp_path/'browser batch.json';a=args(tmp_path,browser_capture=True,file=path)
    path.write_text(json.dumps({'records':[{}]*26}))
    with pytest.raises(RuntimeError,match='25'):manager.import_batch(a)
    path.write_text(json.dumps({'records':[],'batch_id':'expected'}))
    monkeypatch.setattr(manager,'request',lambda *a,**k:{'batch_id':'stale'})
    with pytest.raises(RuntimeError,match='acknowledgement'):manager.import_batch(a)

def test_full_backup_restore_keeps_records_and_previews(tmp_path):
    a=args(tmp_path,output=tmp_path/'backup.tar.gz');_,data=manager.paths(a);data.mkdir(parents=True)
    with sqlite3.connect(data/'library.sqlite') as c:c.execute('CREATE TABLE personal(note TEXT)');c.execute('INSERT INTO personal VALUES(?)',('My note',))
    (data/'.access-key').write_text('test-local-key');(data/'thumbnails').mkdir();(data/'thumbnails'/'sample.jpg').write_bytes(b'invented preview')
    manager.backup(a);a.file=a.output;a.to=tmp_path/'restored with spaces';manager.restore(a)
    assert (a.to/'thumbnails/sample.jpg').read_bytes()==b'invented preview'
    with sqlite3.connect(a.to/'library.sqlite') as c:assert c.execute('SELECT note FROM personal').fetchone()[0]=='My note'
    assert (a.to/'.access-key').read_text()=='test-local-key'
    with pytest.raises(RuntimeError,match='empty'):manager.restore(a)

def test_unsafe_backup_rejected_before_writing(tmp_path):
    archive=tmp_path/'malicious.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        item=tarfile.TarInfo('../outside');item.size=3;t.addfile(item,io.BytesIO(b'bad'))
    a=args(tmp_path,file=archive,to=tmp_path/'restore')
    with pytest.raises(RuntimeError,match='Unsafe'):manager.restore(a)
    assert not a.to.exists()


def test_backup_refuses_to_overwrite_its_database(tmp_path):
    a=args(tmp_path);_,data=manager.paths(a);data.mkdir(parents=True)
    with sqlite3.connect(data/'library.sqlite') as c:c.execute('CREATE TABLE note(value TEXT)')
    a.output=data/'library.sqlite'
    with pytest.raises(RuntimeError,match='overwrite'):manager.backup(a)
    with sqlite3.connect(a.output) as c:assert c.execute('SELECT count(*) FROM note').fetchone()[0]==0

def test_cloud_template_validates_uuid_and_refuses_overwrite(tmp_path):
    output=tmp_path/'generated wrangler.toml'
    a=args(tmp_path,database_id='not-a-uuid',output=output,force=False)
    with pytest.raises(RuntimeError,match='UUID'):manager.cloud_template(a)
    a.database_id='12345678-1234-'+ '5678-1234-567812345678'
    manager.cloud_template(a)
    text=output.read_text()
    assert a.database_id in text and 'REPLACE_' not in text and 'SYNC_SECRET =' not in text
    with pytest.raises(RuntimeError,match='overwrite'):manager.cloud_template(a)

def test_model_status_checks_configured_file_checksum(tmp_path,monkeypatch):
    model=tmp_path/'model.safetensors';model.write_bytes(b'synthetic model fixture')
    manifest=tmp_path/'models.json';manifest.write_text(json.dumps({'version':1,'models':[{
        'id':'fixture','purpose':'test','environment':'SAVEDAGAIN_TEST_MODEL','expected_file':'model.safetensors',
        'sha256':hashlib.sha256(model.read_bytes()).hexdigest()
    }]}))
    monkeypatch.setattr(manager,'MODEL_MANIFEST',manifest);monkeypatch.setenv('SAVEDAGAIN_TEST_MODEL',str(tmp_path))
    assert manager.configured_models()['models'][0]['status']=='ready'
    model.write_bytes(b'changed')
    assert manager.configured_models()['models'][0]['status']=='checksum_mismatch'

def test_doctor_reports_required_and_optional_status(tmp_path,monkeypatch,capsys):
    a=args(tmp_path,json=True)
    monkeypatch.setattr(manager,'command_version',lambda name:(('/bin/'+name,'v24.1.0') if name=='node' else ('/bin/'+name,'10.0.0')))
    monkeypatch.setattr(manager,'voice_studio_status',lambda:{'status':'unavailable','transcription_contract':False})
    monkeypatch.setattr(manager,'configured_models',lambda:{'models':[]})
    assert manager.doctor(a)==0
    report=json.loads(capsys.readouterr().out)
    assert report['node']['status']=='ready' and report['voice_studio']['status']=='unavailable'
