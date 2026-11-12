# Private local reel analysis

Use this workflow only for reel files the user manually attaches or places in the private watched inbox. It does not authorize downloading Instagram media, reading browser cookies, calling private APIs, or bypassing access controls.

## Ingestion

- Manual attachment is available from an item’s detail panel. SavedAgain copies the upload into a temporary private working file and removes that copy when processing ends.
- The watched inbox is `<library>/inbox`. Match a video to a save by including the shortcode in its filename, or add `video.mp4.json` containing `{"shortcode":"…"}` or `{"url":"https://www.instagram.com/reel/…/"}`. Inbox originals are never changed or deleted.
- Accept MP4, MOV, M4V, WebM and MKV files up to 2.5 GB. Validate with ffprobe, hash for provenance, extract 16 kHz mono WAV audio, and retain no more than eight representative frames.
- Only one heavyweight analysis job runs at a time. Jobs and stages persist in SQLite and can resume after interruption.

## Analyzer adapters

Install analyzer code explicitly with `savedagain.py install-analysis`. Exact Python package versions are recorded in `backend/requirements-analysis.txt`; installation can use several GB because PyTorch/Paddle runtimes are included. This command does not install weights. Configure only paths that already exist in a private model cache and run `savedagain.py models` to validate them against [the model manifest](models-manifest.json):

- `SAVEDAGAIN_SENTENCE_MODEL`: local `paraphrase-multilingual-MiniLM-L12-v2` directory.
- `SAVEDAGAIN_OPENCLIP_CHECKPOINT`: local OpenCLIP ViT-B/32 checkpoint file.
- `SAVEDAGAIN_PADDLEOCR_LATIN_MODEL`: local PP-OCRv6 recognition model directory.
- `SAVEDAGAIN_PADDLEOCR_DETECTION_MODEL`: local PP-OCR detection model directory shared by both recognizers.
- `SAVEDAGAIN_PADDLEOCR_DEVANAGARI_MODEL`: local Devanagari PP-OCRv5 recognition model directory. It runs when the caption suggests Devanagari.
- PySceneDetect has no weights and falls back to uniform sampling if its optional package is absent.
- BERTopic runs only from the explicit topic-discovery endpoint and returns proposals; it never changes the taxonomy.
- Set `SAVEDAGAIN_OLLAMA=on` to permit an already-running local Ollama instance to summarize with the already-installed `qwen3:4b`. SavedAgain checks `/api/tags` and never pulls a model.

The pinned MiniLM and OpenCLIP files total about 1.1 GB; Qwen3 4B adds about 2.5 GB, before OCR weights and Python runtimes. Reserve at least 10 GB for a practical complete installation and more for cached reels/frames. CPU-only analysis works but may be slow. Review each upstream model license before downloading it.

Example private configuration (replace every path with your own downloaded model location):

```sh
export SAVEDAGAIN_SENTENCE_MODEL="/private/model-cache/paraphrase-multilingual-MiniLM-L12-v2"
export SAVEDAGAIN_OPENCLIP_CHECKPOINT="/private/model-cache/CLIP-ViT-B-32/model.safetensors"
export SAVEDAGAIN_PADDLEOCR_LATIN_MODEL="/private/model-cache/paddle/latin-rec"
export SAVEDAGAIN_PADDLEOCR_DEVANAGARI_MODEL="/private/model-cache/paddle/devanagari-rec"
export SAVEDAGAIN_PADDLEOCR_DETECTION_MODEL="/private/model-cache/paddle/detection"
python "SKILL/scripts/savedagain.py" models
```

FFmpeg installation examples:

- macOS/Homebrew: `brew install ffmpeg`
- Windows/winget: `winget install --id Gyan.FFmpeg --exact`
- Ubuntu/Debian: `sudo apt-get update && sudo apt-get install ffmpeg`

PaddlePaddle 3.3.1 publishes Python 3.11 wheels for macOS ARM64, Windows x64 and Linux x64. Other CPU/OS combinations remain untested and may require an upstream-supported runtime or leaving OCR unavailable. Adapter availability is not proof that a model has run successfully on a particular platform.

Unavailable adapters become visible stage statuses. They do not block metadata import, overwrite manual filing, or trigger a hosted fallback.

## VoiceStudio transcription only

VoiceStudio is SavedAgain’s sole transcription interface. Default backend: `http://localhost:3900`, overridable with `SAVEDAGAIN_VOICESTUDIO_URL`.

Install and start a released [VoiceStudio](https://github.com/debpalash/VoiceStudio/releases) version separately, then verify its own model manager has a transcription-capable backend ready. SavedAgain discovers the running OpenAPI contract; it does not pin, start, configure or update VoiceStudio.

1. Check `GET /health`.
2. Read `GET /openapi.json` and confirm `POST /v1/audio/transcriptions` exists.
3. Send the extracted WAV as multipart form data with `model=whisper-1` and `response_format=verbose_json`.
4. Store text and segment timestamps locally with `VoiceStudio/whisper-1` provenance.

Do not call VoiceStudio speech, cloning, dubbing, voice design, translation or model-install endpoints. Do not call whisper.cpp directly. If VoiceStudio or its active ASR model is unavailable, mark the job `waiting_for_transcription`, retain the derived WAV locally, finish independent stages, and retry only when the user has made VoiceStudio ready. Never fabricate a transcript or silently download a model.

## Classification fusion

Normalize category scores, renormalize missing modalities, and use these versioned weights:

- Text 50%: caption 40%, transcript 35%, OCR 25%.
- OpenCLIP visual evidence 20%.
- Nearest user-confirmed exemplar 20% when a compatible local embedding exists.
- Transparent keyword and collection fallback 10%.

Auto-file only at score `0.72`, margin `0.15`, and either two independent evidence types or confirmed exemplar/collection evidence. Score `0.55` with margin `0.08` is a reviewable suggestion. Everything else stays in Needs review. Manual categories always win, and explanations must show score, margin, evidence, alternatives, missing stages and model versions.

## Privacy and retention

Raw captions, OCR, transcripts, frames, audio, embeddings, prompts, source paths and detailed model output remain local. The cloud projection may contain only the generated title/summary, tags, category data, state fields and compressed thumbnail. Backups include the derived local analysis directory but never automatically add inbox originals or temporary uploads.
