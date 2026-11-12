import importlib.util,re
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release',ROOT/'scripts/build_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

def test_allowlist_and_local_skill_references():
    assert release.allowlisted()
    skill=ROOT/'skills/saved-again';text=(skill/'SKILL.md').read_text()
    assert text.startswith('---\nname: saved-again\n')
    for target in re.findall(r'\]\(([^)]+)\)',text):
        if not target.startswith('https:'):assert (skill/target).exists(),target

def test_release_audit_rejects_machine_paths_and_private_fingerprints(tmp_path):
    with pytest.raises(ValueError,match='privacy'):release.audit([('bad.txt',b'/'+b'Users/'+b'example/private')])
    (tmp_path/'.access-key').write_text('a-fake-test-secret')
    with pytest.raises(ValueError,match='privacy'):release.audit([('leaked.txt',b'a-fake-test-secret')],tmp_path)
    release.audit([('clean.txt',b'Synthetic public example')],tmp_path)

def test_release_version_is_validated(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'allowlisted',lambda:[('README.md',ROOT/'README.md')])
    with pytest.raises(ValueError,match='Version'):release.build(tmp_path,version='../bad')
