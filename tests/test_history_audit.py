import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('history_audit',ROOT/'scripts/audit_history.py')
history_audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(history_audit)

def test_history_audit_detects_private_files_and_secrets():
    assert 'forbidden private/runtime filename' in history_audit.inspect_blob('private/.env',b'SAFE=value')
    assert 'absolute macOS user path' in history_audit.inspect_blob('docs/example.txt',b'/'+b'Users/example/SavedAgain')
    assert 'private key' in history_audit.inspect_blob('fixture.txt',b'-----BEGIN PRIVATE '+b'KEY-----')
    cloud_id=b'a'*32
    assert 'committed Cloudflare resource identifier' in history_audit.inspect_blob('wrangler.toml',b'account_id = "'+cloud_id+b'"')

def test_history_audit_accepts_synthetic_public_content():
    assert history_audit.inspect_blob('docs/demo.json',b'{"account":"@synthetic_demo"}')==[]
