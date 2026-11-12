import json
import sqlite3

import httpx
import pytest

from backend import analysis
from backend.analysis import AnalysisUnavailable, VoiceStudioTranscriber, match_inbox_entry


class FakeClient:
    calls = []

    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): return False

    def get(self, url):
        self.calls.append(("GET", url))
        if url.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"paths": {"/v1/audio/transcriptions": {"post": {}}}}, request=httpx.Request("GET", url))

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs["data"]))
        return httpx.Response(200, json={"text": "Synthetic transcript", "segments": [{"start": 0, "end": 1, "text": "Synthetic transcript"}]}, request=httpx.Request("POST", url))


def test_voicestudio_is_the_only_transcription_interface(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"; audio.write_bytes(b"RIFFsynthetic")
    FakeClient.calls = []
    monkeypatch.setattr("backend.analysis.httpx.Client", FakeClient)
    result = VoiceStudioTranscriber().transcribe(audio)
    assert result["text"] == "Synthetic transcript"
    assert [call[:2] for call in FakeClient.calls] == [
        ("GET", "http://localhost:3900/health"),
        ("GET", "http://localhost:3900/openapi.json"),
        ("POST", "http://localhost:3900/v1/audio/transcriptions"),
    ]
    assert FakeClient.calls[-1][2] == {"model": "whisper-1", "response_format": "verbose_json"}


def test_voicestudio_missing_contract_is_retryable(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"; audio.write_bytes(b"RIFFsynthetic")
    class Missing(FakeClient):
        def get(self, url):
            if url.endswith("/openapi.json"):
                return httpx.Response(200, json={"paths": {}}, request=httpx.Request("GET", url))
            return super().get(url)
    monkeypatch.setattr("backend.analysis.httpx.Client", Missing)
    with pytest.raises(AnalysisUnavailable, match="does not advertise"):
        VoiceStudioTranscriber().transcribe(audio)


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "malformed_schema", "missing_model", "malformed_payload"])
def test_voicestudio_contract_failures_are_retryable(tmp_path, monkeypatch, failure):
    audio = tmp_path / "clip.wav"; audio.write_bytes(b"RIFFsynthetic")

    class FailureClient(FakeClient):
        def get(self, url):
            if failure == "unavailable" and url.endswith("/health"):
                raise httpx.ConnectError("offline", request=httpx.Request("GET", url))
            if failure == "timeout" and url.endswith("/health"):
                raise httpx.ReadTimeout("timeout", request=httpx.Request("GET", url))
            if failure == "malformed_schema" and url.endswith("/openapi.json"):
                return httpx.Response(200, content=b"not-json", request=httpx.Request("GET", url))
            return super().get(url)

        def post(self, url, **kwargs):
            if failure == "missing_model":
                return httpx.Response(503, text="ASR model unavailable", request=httpx.Request("POST", url))
            if failure == "malformed_payload":
                return httpx.Response(200, content=b"not-json", request=httpx.Request("POST", url))
            return super().post(url, **kwargs)

    monkeypatch.setattr("backend.analysis.httpx.Client", FailureClient)
    with pytest.raises(AnalysisUnavailable):VoiceStudioTranscriber().transcribe(audio)


def test_transcription_failure_keeps_partial_analysis(tmp_path, monkeypatch):
    database = tmp_path / "analysis.sqlite";source = tmp_path / "SyntheticReel01.mp4";source.write_bytes(b"synthetic video")

    def connection_factory():
        connection=sqlite3.connect(database);connection.row_factory=sqlite3.Row;return connection

    with connection_factory() as connection:
        connection.executescript("""
        CREATE TABLE analysis_jobs(id TEXT PRIMARY KEY,post_id TEXT,source_path TEXT,source_kind TEXT,status TEXT,stage TEXT,created TEXT,updated TEXT,source_sha256 TEXT,error TEXT,stages TEXT);
        CREATE TABLE analysis_artifacts(job_id TEXT,post_id TEXT,kind TEXT,content TEXT,model TEXT,provenance TEXT,created TEXT);
        CREATE TABLE posts(id TEXT PRIMARY KEY,data TEXT);
        CREATE TABLE embeddings(post_id TEXT,modality TEXT,model TEXT,vector TEXT,created TEXT,PRIMARY KEY(post_id,modality,model));
        """)
        connection.execute("INSERT INTO posts VALUES(?,?)",("SyntheticReel01",json.dumps({"caption":"simple synthetic reference","collections":[]})))
        job_id=analysis.create_job(connection,"SyntheticReel01",source,"inbox")

    def extract(*args):
        work=args[1];work.mkdir(parents=True);audio=work/"audio.wav";audio.write_bytes(b"RIFFsynthetic")
        return [],audio,{"timestamps":[],"sampler":"test"}

    monkeypatch.setattr(analysis,"probe_media",lambda path:{"duration":1,"video":True})
    monkeypatch.setattr(analysis,"extract_media",extract)
    monkeypatch.setattr(analysis.VoiceStudioTranscriber,"transcribe",lambda self,path:(_ for _ in ()).throw(AnalysisUnavailable("VoiceStudio offline")))
    monkeypatch.setattr(analysis,"paddle_ocr",lambda *a,**k:(_ for _ in ()).throw(AnalysisUnavailable("OCR unavailable")))
    monkeypatch.setattr(analysis,"openclip_scores",lambda *a,**k:(_ for _ in ()).throw(AnalysisUnavailable("visual unavailable")))
    monkeypatch.setattr(analysis,"semantic_scores",lambda *a,**k:(_ for _ in ()).throw(AnalysisUnavailable("semantic unavailable")))
    monkeypatch.setattr(analysis,"ollama_summary",lambda text:None)
    applied=[]
    analysis.process_job(job_id,connection_factory=connection_factory,data_dir=tmp_path,category_labels=lambda:{"review":"Needs review"},apply_result=lambda *args:applied.append(args))
    with connection_factory() as connection:
        row=connection.execute("SELECT status,stages FROM analysis_jobs WHERE id=?",(job_id,)).fetchone()
        artifacts={item[0] for item in connection.execute("SELECT kind FROM analysis_artifacts WHERE job_id=?",(job_id,))}
    assert row["status"]=="waiting_for_transcription" and applied
    assert {"media_probe","classification"}<=artifacts
    assert json.loads(row["stages"])["ocr"]["status"]=="unavailable"


def test_inbox_matches_filename_or_sidecar(tmp_path):
    direct = tmp_path / "SyntheticReel01.mp4"
    direct.write_bytes(b"video")
    assert match_inbox_entry(direct) == "SyntheticReel01"
    sidecar = tmp_path / "my-video.mov"
    sidecar.write_bytes(b"video")
    sidecar.with_suffix(".mov.json").write_text(json.dumps({"url": "https://www.instagram.com/reel/Sidecar002/"}))
    assert match_inbox_entry(sidecar) == "Sidecar002"
