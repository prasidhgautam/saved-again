"""Private, resumable reel analysis.

All heavyweight dependencies are lazy and all model loads are local-only. This
module never downloads Instagram media or model weights.
"""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from .classify import analyze as keyword_analyze
from .fusion import fuse_category_scores


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
SHORTCODE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{3,120})(?![A-Za-z0-9_-])")
INSTAGRAM_URL = re.compile(r"https://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reel)/([A-Za-z0-9_-]{3,120})/?")
VOICE_STUDIO_DEFAULT = "http://localhost:3900"
MAX_SOURCE_BYTES = 2_500_000_000
MAX_FRAMES = 8


class AnalysisUnavailable(RuntimeError):
    """A retryable analyzer dependency or model is unavailable."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS analysis_jobs(
          id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          source_path TEXT NOT NULL, source_kind TEXT NOT NULL, source_sha256 TEXT,
          status TEXT NOT NULL, stage TEXT NOT NULL, stages TEXT NOT NULL DEFAULT '{}',
          error TEXT, created TEXT NOT NULL, updated TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS analysis_jobs_post ON analysis_jobs(post_id,updated DESC);
        CREATE TABLE IF NOT EXISTS analysis_artifacts(
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
          post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, kind TEXT NOT NULL,
          content TEXT NOT NULL, model TEXT, provenance TEXT NOT NULL, created TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS analysis_artifacts_post ON analysis_artifacts(post_id,kind,created DESC);
        CREATE TABLE IF NOT EXISTS embeddings(
          post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, modality TEXT NOT NULL,
          model TEXT NOT NULL, vector TEXT NOT NULL, created TEXT NOT NULL,
          PRIMARY KEY(post_id,modality,model)
        );
        """
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def probe_media(path: Path) -> dict:
    if path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError("Attach an MP4, MOV, M4V, WebM, or MKV video.")
    if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("The attached video is empty or exceeds the 2.5 GB local limit.")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise AnalysisUnavailable("FFmpeg/ffprobe is required for local reel analysis.")
    result = _run([
        ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ])
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError("The attachment does not contain a video stream.")
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        duration = max((float(stream.get("duration") or 0) for stream in streams), default=0)
    return {
        "duration": duration,
        "size": path.stat().st_size,
        "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "streams": [{key: stream.get(key) for key in ("codec_type", "codec_name", "width", "height", "duration")} for stream in streams],
    }


def _uniform_timestamps(duration: float, count: int = MAX_FRAMES) -> list[float]:
    if duration <= 0:
        return [0.0]
    amount = min(count, max(3, math.ceil(duration / 12)))
    return [round(duration * index / max(1, amount - 1), 3) for index in range(amount)]


def scene_timestamps(path: Path, duration: float) -> tuple[list[float], str]:
    try:
        from scenedetect import AdaptiveDetector, detect

        scenes = detect(str(path), AdaptiveDetector(), show_progress=False)
        candidates = [start.get_seconds() for start, _ in scenes]
        candidates.extend(_uniform_timestamps(duration, 3))
        unique = sorted({round(max(0.0, min(duration, stamp)), 3) for stamp in candidates})
        if len(unique) > MAX_FRAMES:
            stride = (len(unique) - 1) / (MAX_FRAMES - 1)
            unique = [unique[round(index * stride)] for index in range(MAX_FRAMES)]
        return unique or [0.0], "PySceneDetect AdaptiveDetector"
    except ImportError:
        return _uniform_timestamps(duration), "uniform fallback"
    except Exception:
        return _uniform_timestamps(duration), "uniform fallback after scene detection error"


def extract_media(path: Path, work: Path, duration: float) -> tuple[list[Path], Path | None, dict]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AnalysisUnavailable("FFmpeg is required for frame and audio extraction.")
    work.mkdir(parents=True, exist_ok=True)
    stamps, sampler = scene_timestamps(path, duration)
    frames: list[Path] = []
    for index, stamp in enumerate(stamps[:MAX_FRAMES]):
        destination = work / f"frame-{index:02d}.jpg"
        try:
            _run([ffmpeg, "-y", "-ss", str(stamp), "-i", str(path), "-frames:v", "1", "-q:v", "3", str(destination)], timeout=90)
            if destination.exists() and destination.stat().st_size:
                frames.append(destination)
        except (subprocess.SubprocessError, OSError):
            continue
    audio = work / "audio.wav"
    try:
        _run([ffmpeg, "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)])
        if not audio.exists() or not audio.stat().st_size:
            audio = None
    except (subprocess.SubprocessError, OSError):
        audio = None
    return frames, audio, {"timestamps": stamps[:MAX_FRAMES], "sampler": sampler}


class VoiceStudioTranscriber:
    """The sole SavedAgain transcription interface."""

    def __init__(self, base_url: str | None = None, timeout: float = 180.0):
        self.base_url = (base_url or os.environ.get("SAVEDAGAIN_VOICESTUDIO_URL") or VOICE_STUDIO_DEFAULT).rstrip("/")
        self.timeout = timeout

    def transcribe(self, audio: Path) -> dict:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                health = client.get(f"{self.base_url}/health")
                health.raise_for_status()
                schema_response = client.get(f"{self.base_url}/openapi.json")
                schema_response.raise_for_status()
                schema = schema_response.json()
                operation = (schema.get("paths") or {}).get("/v1/audio/transcriptions", {}).get("post")
                if operation is None:
                    raise AnalysisUnavailable("VoiceStudio does not advertise /v1/audio/transcriptions in its running schema.")
                with audio.open("rb") as stream:
                    response = client.post(
                        f"{self.base_url}/v1/audio/transcriptions",
                        data={"model": "whisper-1", "response_format": "verbose_json"},
                        files={"file": (audio.name, stream, "audio/wav")},
                    )
                if response.status_code >= 400:
                    detail = response.text[:500]
                    raise AnalysisUnavailable(f"VoiceStudio transcription is not ready: HTTP {response.status_code}: {detail}")
                payload = response.json()
        except AnalysisUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise AnalysisUnavailable(f"VoiceStudio is unavailable or returned an invalid response: {error}") from error
        text = str(payload.get("text") or "").strip()
        if not text:
            raise AnalysisUnavailable("VoiceStudio returned no transcript text.")
        segments = [
            {"start": segment.get("start"), "end": segment.get("end"), "text": str(segment.get("text") or "").strip()}
            for segment in payload.get("segments") or []
        ]
        return {"text": text, "segments": segments, "language": payload.get("language"), "model": "whisper-1"}


def _local_sentence_model():
    model_path = os.environ.get("SAVEDAGAIN_SENTENCE_MODEL")
    if not model_path or not Path(model_path).exists():
        raise AnalysisUnavailable("The multilingual MiniLM model is not installed in the configured private cache.")
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_path, local_files_only=True)
    except ImportError as error:
        raise AnalysisUnavailable("Install the optional analysis dependencies to use Sentence Transformers.") from error


def semantic_scores(text: str, labels: dict[str, str]) -> tuple[dict[str, float], list[float] | None]:
    if not text.strip() or not labels:
        return {}, None
    model = _local_sentence_model()
    vectors = model.encode([text, *labels.values()], normalize_embeddings=True)
    query = vectors[0]
    scores = {category: max(0.0, min(1.0, (float(query @ vector) + 1.0) / 2.0)) for category, vector in zip(labels, vectors[1:])}
    return scores, [float(value) for value in query]


def paddle_ocr(frames: list[Path], devanagari_hint: bool = False) -> dict:
    latin_dir = os.environ.get("SAVEDAGAIN_PADDLEOCR_LATIN_MODEL")
    devanagari_dir = os.environ.get("SAVEDAGAIN_PADDLEOCR_DEVANAGARI_MODEL")
    detection_dir = os.environ.get("SAVEDAGAIN_PADDLEOCR_DETECTION_MODEL")
    if not latin_dir or not Path(latin_dir).exists() or not detection_dir or not Path(detection_dir).exists():
        raise AnalysisUnavailable("PaddleOCR model directories are not configured; no model was downloaded.")
    try:
        from paddleocr import PaddleOCR
    except ImportError as error:
        raise AnalysisUnavailable("Install the optional analysis dependencies to use PaddleOCR.") from error

    def read(model_dir: str) -> list[str]:
        engine = PaddleOCR(text_detection_model_dir=detection_dir, text_recognition_model_dir=model_dir, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
        found: list[str] = []
        for frame in frames:
            result = engine.predict(str(frame))
            for page in result or []:
                payload = getattr(page, "json", page)
                if callable(payload):
                    payload = payload()
                if isinstance(payload, str):
                    payload = json.loads(payload)
                data = payload.get("res", payload) if isinstance(payload, dict) else {}
                found.extend(str(value).strip() for value in data.get("rec_texts", []) if str(value).strip())
        return found

    text = read(latin_dir)
    engines = ["PP-OCRv6/Latin"]
    if devanagari_hint and devanagari_dir and Path(devanagari_dir).exists():
        text.extend(read(devanagari_dir))
        engines.append("Devanagari PP-OCRv5")
    return {"text": "\n".join(dict.fromkeys(text)), "engines": engines}


def openclip_scores(frames: list[Path], labels: dict[str, str]) -> dict[str, float]:
    checkpoint = os.environ.get("SAVEDAGAIN_OPENCLIP_CHECKPOINT")
    if not checkpoint or not Path(checkpoint).exists():
        raise AnalysisUnavailable("The OpenCLIP checkpoint is not installed in the configured private cache.")
    try:
        import open_clip
        import torch
        from PIL import Image
    except ImportError as error:
        raise AnalysisUnavailable("Install the optional analysis dependencies to use OpenCLIP.") from error
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained=checkpoint)
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    images = torch.stack([preprocess(Image.open(frame).convert("RGB")) for frame in frames])
    prompts = [f"A saved reel mainly about {label}" for label in labels.values()]
    with torch.no_grad():
        image_features = model.encode_image(images)
        text_features = model.encode_text(tokenizer(prompts))
        image_features /= image_features.norm(dim=-1, keepdim=True)
        text_features /= text_features.norm(dim=-1, keepdim=True)
        similarities = (image_features @ text_features.T).mean(dim=0).softmax(dim=-1)
    return {category: float(score) for category, score in zip(labels, similarities)}


def ollama_summary(evidence: str) -> dict | None:
    if not evidence.strip() or os.environ.get("SAVEDAGAIN_OLLAMA", "off").lower() not in {"1", "true", "on"}:
        return None
    base = os.environ.get("SAVEDAGAIN_OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("SAVEDAGAIN_OLLAMA_MODEL", "qwen3:4b")
    try:
        with httpx.Client(timeout=90) as client:
            tags = client.get(f"{base}/api/tags")
            tags.raise_for_status()
            installed = {item.get("name") for item in tags.json().get("models", [])}
            if model not in installed and not any(name and name.startswith(model + ":") for name in installed):
                return None
            response = client.post(f"{base}/api/chat", json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "user", "content": "Return JSON with a short factual title, summary, and tags based only on this evidence:\n" + evidence[:12000]}],
            })
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "{}")
            parsed = json.loads(content)
            return {"title": str(parsed.get("title") or "")[:120], "summary": str(parsed.get("summary") or "")[:600], "tags": list(parsed.get("tags") or [])[:12], "model": model}
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def match_inbox_entry(path: Path, known_ids: set[str] | None = None) -> str | None:
    """Match a video to a shortcode without deleting or modifying the source."""
    sidecar = path.with_suffix(path.suffix + ".json")
    alternate = path.with_suffix(".json")
    for candidate in dict.fromkeys((sidecar, alternate)):
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shortcode = str(payload.get("shortcode") or payload.get("id") or "")
        url_match = INSTAGRAM_URL.search(str(payload.get("url") or ""))
        if re.fullmatch(r"[A-Za-z0-9_-]{3,120}", shortcode):
            return shortcode
        if url_match:
            return url_match.group(1)
    url_match = INSTAGRAM_URL.search(path.stem)
    if url_match:
        return url_match.group(1)
    if known_ids:
        matches = [post_id for post_id in known_ids if post_id in path.stem]
        if matches:
            return max(matches, key=len)
    matches = SHORTCODE.findall(path.stem)
    return max(matches, key=len) if matches else None


def add_artifact(connection, job_id: str, post_id: str, kind: str, content, model: str | None, provenance: str) -> None:
    connection.execute(
        "INSERT INTO analysis_artifacts(job_id,post_id,kind,content,model,provenance,created) VALUES(?,?,?,?,?,?,?)",
        (job_id, post_id, kind, json.dumps(content, ensure_ascii=False), model, provenance, utcnow()),
    )


def create_job(connection, post_id: str, source_path: Path, source_kind: str) -> str:
    job_id = uuid.uuid4().hex
    stamp = utcnow()
    connection.execute(
        "INSERT INTO analysis_jobs(id,post_id,source_path,source_kind,status,stage,created,updated) VALUES(?,?,?,?,?,?,?,?)",
        (job_id, post_id, str(source_path), source_kind, "queued", "queued", stamp, stamp),
    )
    return job_id


def _stage(connection, job_id: str, stage: str, status: str = "running", error: str | None = None) -> None:
    connection.execute(
        "UPDATE analysis_jobs SET stage=?,status=?,error=?,updated=? WHERE id=?",
        (stage, status, error, utcnow(), job_id),
    )


def process_job(
    job_id: str,
    *,
    connection_factory: Callable,
    data_dir: Path,
    category_labels: Callable[[], dict[str, str]],
    apply_result: Callable[[str, dict], None],
    exemplar_scores: Callable[[str, list[float]], dict[str, float]] | None = None,
) -> None:
    with connection_factory() as connection:
        row = connection.execute("SELECT * FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return
        post_id, source_path, source_kind = row["post_id"], Path(row["source_path"]), row["source_kind"]
        _stage(connection, job_id, "validating")
    work = data_dir / "analysis" / job_id
    waiting_transcript = None
    stages: dict[str, dict] = {}
    try:
        media = probe_media(source_path)
        digest = sha256_file(source_path)
        with connection_factory() as connection:
            connection.execute("UPDATE analysis_jobs SET source_sha256=?,updated=? WHERE id=?", (digest, utcnow(), job_id))
            add_artifact(connection, job_id, post_id, "media_probe", media, "ffprobe", "user-provided local file")
            _stage(connection, job_id, "extracting")
        frames, audio, sampling = extract_media(source_path, work, media["duration"])
        stages["media"] = {"status": "complete", "frames": len(frames), **sampling}

        transcript = None
        if audio:
            try:
                transcript = VoiceStudioTranscriber().transcribe(audio)
                stages["transcript"] = {"status": "complete", "model": "VoiceStudio/whisper-1"}
                with connection_factory() as connection:
                    add_artifact(connection, job_id, post_id, "transcript", transcript, "VoiceStudio/whisper-1", "extracted 16 kHz mono WAV")
            except AnalysisUnavailable as error:
                waiting_transcript = str(error)
                stages["transcript"] = {"status": "waiting", "error": waiting_transcript}
        else:
            stages["transcript"] = {"status": "unavailable", "error": "The video contains no extractable audio."}

        with connection_factory() as connection:
            post = connection.execute("SELECT data FROM posts WHERE id=?", (post_id,)).fetchone()
        record = json.loads(post[0]) if post else {}
        labels = category_labels()
        devanagari = bool(re.search(r"[\u0900-\u097F]", str(record.get("caption") or "")))

        ocr = None
        try:
            ocr = paddle_ocr(frames, devanagari_hint=devanagari)
            stages["ocr"] = {"status": "complete", "models": ocr["engines"]}
            with connection_factory() as connection:
                add_artifact(connection, job_id, post_id, "ocr", ocr, ", ".join(ocr["engines"]), "representative frames")
        except AnalysisUnavailable as error:
            stages["ocr"] = {"status": "unavailable", "error": str(error)}

        visual_scores = {}
        try:
            visual_scores = openclip_scores(frames, labels)
            stages["visual"] = {"status": "complete", "model": "OpenCLIP ViT-B-32"}
        except AnalysisUnavailable as error:
            stages["visual"] = {"status": "unavailable", "error": str(error)}

        semantic: dict[str, dict] = {}
        embeddings: dict[str, list[float]] = {}
        text_inputs = {
            "caption": str(record.get("caption") or ""),
            "transcript": str((transcript or {}).get("text") or ""),
            "ocr": str((ocr or {}).get("text") or ""),
        }
        for modality, text in text_inputs.items():
            if not text:
                continue
            try:
                scores, vector = semantic_scores(text, labels)
                semantic[modality] = scores
                if vector:
                    embeddings[modality] = vector
            except AnalysisUnavailable as error:
                stages.setdefault("semantic", {"status": "unavailable", "error": str(error)})
                break
        if semantic:
            stages["semantic"] = {"status": "complete", "model": "paraphrase-multilingual-MiniLM-L12-v2"}

        fallback_record = {**record, "caption": "\n".join(value for value in text_inputs.values() if value)}
        fallback_result = keyword_analyze(fallback_record)
        fallback_scores = {fallback_result["category"]: 0.8 if fallback_result["classification_confidence"] == "high" else 0.6}
        exemplar = exemplar_scores("caption", embeddings["caption"]) if exemplar_scores and embeddings.get("caption") else {}
        collection_result = keyword_analyze({"id": post_id, "caption": "", "collections": record.get("collections", [])})
        collection_confirmed = bool(record.get("collections")) and collection_result["category"] == fallback_result["category"] and collection_result["category"] != "review"
        fusion = fuse_category_scores(
            caption=semantic.get("caption"), transcript=semantic.get("transcript"), ocr=semantic.get("ocr"),
            visual=visual_scores, exemplar=exemplar, fallback=fallback_scores, collection_confirmed=collection_confirmed,
        ).as_dict()
        summary = ollama_summary("\n".join(value for value in text_inputs.values() if value))
        result = {"fusion": fusion, "stages": stages, "summary": summary, "analyzed_at": utcnow()}
        with connection_factory() as connection:
            for modality, vector in embeddings.items():
                connection.execute(
                    "INSERT OR REPLACE INTO embeddings(post_id,modality,model,vector,created) VALUES(?,?,?,?,?)",
                    (post_id, modality, "paraphrase-multilingual-MiniLM-L12-v2", json.dumps(vector), utcnow()),
                )
            add_artifact(connection, job_id, post_id, "classification", result, fusion["version"], "multimodal fusion")
        apply_result(post_id, result)
        final_status = "waiting_for_transcription" if waiting_transcript else "complete"
        with connection_factory() as connection:
            connection.execute(
                "UPDATE analysis_jobs SET status=?,stage=?,stages=?,error=?,updated=? WHERE id=?",
                (final_status, final_status, json.dumps(stages), waiting_transcript, utcnow(), job_id),
            )
    except AnalysisUnavailable as error:
        with connection_factory() as connection:
            _stage(connection, job_id, "waiting_for_dependency", "waiting", str(error))
    except Exception as error:
        with connection_factory() as connection:
            _stage(connection, job_id, "failed", "failed", str(error)[:1000])
    finally:
        if source_kind == "manual" and source_path.parent.name == "uploads":
            source_path.unlink(missing_ok=True)


def retry_transcription_job(job_id: str, *, connection_factory: Callable, apply_result: Callable[[str, dict], None]) -> None:
    """Resume only VoiceStudio transcription from the retained derived WAV."""
    with connection_factory() as connection:
        row = connection.execute("SELECT * FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return
        post_id = row["post_id"]
        stages = json.loads(row["stages"] or "{}")
        audio = Path(row["source_path"]).parent.parent / "analysis" / job_id / "audio.wav"
        _stage(connection, job_id, "transcribing")
    if not audio.exists():
        with connection_factory() as connection:
            _stage(connection, job_id, "failed", "failed", "The retained analysis audio is unavailable; attach the reel again.")
        return
    try:
        transcript = VoiceStudioTranscriber().transcribe(audio)
        stages["transcript"] = {"status": "complete", "model": "VoiceStudio/whisper-1"}
        with connection_factory() as connection:
            add_artifact(connection, job_id, post_id, "transcript", transcript, "VoiceStudio/whisper-1", "retained 16 kHz mono analysis WAV")
            connection.execute(
                "UPDATE analysis_jobs SET status='complete',stage='complete',stages=?,error=NULL,updated=? WHERE id=?",
                (json.dumps(stages), utcnow(), job_id),
            )
        apply_result(post_id, {"stages": stages, "transcript_resumed_at": utcnow()})
    except AnalysisUnavailable as error:
        stages["transcript"] = {"status": "waiting", "error": str(error)}
        with connection_factory() as connection:
            connection.execute(
                "UPDATE analysis_jobs SET status='waiting_for_transcription',stage='waiting_for_transcription',stages=?,error=?,updated=? WHERE id=?",
                (json.dumps(stages), str(error), utcnow(), job_id),
            )


def discover_topics(embeddings: list[list[float]], texts: list[str]) -> list[dict]:
    if len(embeddings) < 5:
        raise ValueError("At least five Needs review items with local embeddings are required.")
    try:
        from bertopic import BERTopic
    except ImportError as error:
        raise AnalysisUnavailable("Install the optional analysis dependencies to use BERTopic.") from error
    model = BERTopic(calculate_probabilities=False, verbose=False)
    topics, _ = model.fit_transform(texts, embeddings)
    labels = model.get_topic_info().set_index("Topic").to_dict("index")
    return [{"item": index, "topic": int(topic), "label": labels.get(topic, {}).get("Name", "Outlier")} for index, topic in enumerate(topics)]
