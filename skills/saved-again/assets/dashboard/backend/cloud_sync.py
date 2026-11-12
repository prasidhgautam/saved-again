"""Privacy-filtered synchronization with the optional Cloudflare mirror."""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx


SAFE_DATA_FIELDS = {
    "id", "url", "creator", "title", "summary", "tags", "category", "subcategory",
    "categories", "classification_confidence", "organization_status", "media_type",
    "order",
}
SAFE_STATE_FIELDS = {"favourite", "tried", "dismissed", "snoozed_until", "notes", "manual_category"}
FORBIDDEN_FIELDS = {
    "caption", "raw_caption", "ocr", "ocr_text", "transcript", "segments", "frames", "audio",
    "embeddings", "vector", "source_path", "prompt", "analysis_artifacts", "thumbnail_url",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS cloud_sync(
          post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
          remote_revision INTEGER NOT NULL DEFAULT 0, projection_hash TEXT,
          preview_hash TEXT, preview_source_hash TEXT, last_synced TEXT, last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS sync_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS applied_mutations(
          mutation_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL
        );
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_sync)")}
    if "preview_source_hash" not in columns:
        connection.execute("ALTER TABLE cloud_sync ADD COLUMN preview_source_hash TEXT")


def safe_projection(row, data: dict) -> dict:
    projection = {key: data.get(key) for key in SAFE_DATA_FIELDS if data.get(key) is not None}
    projection.update({key: row[key] for key in SAFE_STATE_FIELDS if key in row.keys()})
    projection["id"] = row["id"]
    projection["position"] = row["position"]
    projection["updated"] = row["updated"]
    projection["revision"] = row["revision"] if "revision" in row.keys() else 0
    assert_private_fields_absent(projection)
    return projection


def assert_private_fields_absent(payload) -> None:
    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                lower = str(key).lower()
                if lower in FORBIDDEN_FIELDS or any(token in lower for token in ("transcript", "embedding", "source_path", "raw_caption")):
                    raise ValueError(f"Private field cannot be synchronized: {path + str(key)}")
                walk(child, path + str(key) + ".")
        elif isinstance(value, list):
            for child in value:
                walk(child, path)
    walk(payload)


def projection_hash(projection: dict) -> str:
    return hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def webp_preview(source: Path) -> tuple[bytes, str]:
    try:
        from PIL import Image, ImageOps
    except ImportError as error:
        raise RuntimeError("Pillow is required to create private cloud previews.") from error
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((640, 640))
        output = io.BytesIO()
        image.save(output, "WEBP", quality=75, method=6, exif=b"", icc_profile=None)
    blob = output.getvalue()
    return blob, hashlib.sha256(blob).hexdigest()


class CloudSyncClient:
    def __init__(self):
        self.base_url = os.environ.get("SAVEDAGAIN_CLOUD_URL", "").rstrip("/")
        self.sync_secret = os.environ.get("SAVEDAGAIN_SYNC_SECRET", "")
        self.client_id = os.environ.get("CF_ACCESS_CLIENT_ID", "")
        self.client_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.sync_secret and self.client_id and self.client_secret)

    def _headers(self) -> dict[str, str]:
        return {
            "CF-Access-Client-Id": self.client_id,
            "CF-Access-Client-Secret": self.client_secret,
            "X-SavedAgain-Sync-Secret": self.sync_secret,
        }

    def pull(self, cursor: int) -> dict:
        with httpx.Client(timeout=45, headers=self._headers()) as client:
            response = client.get(f"{self.base_url}/api/sync/pull", params={"after": cursor})
            response.raise_for_status()
            return response.json()

    def push(self, items: list[dict], categories: list[dict]) -> dict:
        assert_private_fields_absent(items)
        with httpx.Client(timeout=60, headers=self._headers()) as client:
            response = client.post(f"{self.base_url}/api/sync/push", json={"items": items, "categories": categories})
            if response.status_code == 409:
                payload = response.json()
                return {"conflicts": payload.get("conflicts", []), "accepted": payload.get("accepted", [])}
            response.raise_for_status()
            return response.json()

    def upload_preview(self, post_id: str, blob: bytes, digest: str) -> None:
        with httpx.Client(timeout=60, headers={**self._headers(), "Content-Type": "image/webp", "X-Content-SHA256": digest}) as client:
            response = client.put(f"{self.base_url}/api/sync/previews/{post_id}", content=blob)
            response.raise_for_status()

    def acknowledge(self, cursor: int) -> None:
        with httpx.Client(timeout=30, headers=self._headers()) as client:
            response = client.post(f"{self.base_url}/api/sync/ack", json={"cursor": cursor})
            response.raise_for_status()


def run_sync(connection_factory, data_dir: Path, apply_remote) -> dict:
    client = CloudSyncClient()
    if not client.configured:
        return {"configured": False, "status": "disabled", "message": "Set the Cloudflare URL, Access service token, and sync secret to enable cloud sync."}
    with connection_factory() as connection:
        cursor_row = connection.execute("SELECT value FROM sync_meta WHERE key='cursor'").fetchone()
        cursor = int(cursor_row[0]) if cursor_row else 0
    pulled = client.pull(cursor)
    for mutation in pulled.get("mutations", []):
        mutation_id = str(mutation.get("id") or "")
        if not mutation_id:
            continue
        with connection_factory() as connection:
            if connection.execute("SELECT 1 FROM applied_mutations WHERE mutation_id=?", (mutation_id,)).fetchone():
                continue
        apply_remote(mutation)
        with connection_factory() as connection:
            connection.execute("INSERT OR IGNORE INTO applied_mutations VALUES(?,?)", (mutation_id, utcnow()))
            if mutation.get("revision") is not None:
                connection.execute(
                    "INSERT INTO cloud_sync(post_id,remote_revision,last_synced) VALUES(?,?,?) "
                    "ON CONFLICT(post_id) DO UPDATE SET remote_revision=excluded.remote_revision,last_synced=excluded.last_synced",
                    (mutation.get("post_id"), int(mutation["revision"]), utcnow()),
                )
    next_cursor = int(pulled.get("cursor", cursor))

    items = []
    with connection_factory() as connection:
        rows = connection.execute(
            "SELECT p.*,s.remote_revision,s.projection_hash FROM posts p LEFT JOIN cloud_sync s ON s.post_id=p.id ORDER BY p.position"
        ).fetchall()
        for row in rows:
            projection = safe_projection(row, json.loads(row["data"]))
            digest = projection_hash(projection)
            if digest != row["projection_hash"]:
                projection["expected_remote_revision"] = row["remote_revision"] or 0
                projection["sync_id"] = digest
                items.append(projection)
        categories = [dict(row) for row in connection.execute("SELECT id,name,art,color,rank FROM categories ORDER BY rank,id")]
    response = client.push(items, categories) if items or categories else {"accepted": [], "conflicts": []}
    accepted = {item["id"]: item for item in response.get("accepted", [])}
    with connection_factory() as connection:
        for row in rows:
            if row["id"] not in accepted:
                continue
            projection = safe_projection(row, json.loads(row["data"]))
            connection.execute(
                "INSERT INTO cloud_sync(post_id,remote_revision,projection_hash,last_synced,last_error) VALUES(?,?,?,?,NULL) "
                "ON CONFLICT(post_id) DO UPDATE SET remote_revision=excluded.remote_revision,projection_hash=excluded.projection_hash,last_synced=excluded.last_synced,last_error=NULL",
                (row["id"], accepted[row["id"]]["revision"], projection_hash(projection), utcnow()),
            )

    preview_count = 0
    for row in rows:
        source = data_dir / "thumbnails" / f"{row['id']}.jpg"
        if not source.exists():
            continue
        try:
            stat = source.stat()
            source_digest = f"{stat.st_mtime_ns}:{stat.st_size}"
            with connection_factory() as connection:
                state = connection.execute("SELECT preview_source_hash FROM cloud_sync WHERE post_id=?", (row["id"],)).fetchone()
            if state and state[0] == source_digest:
                continue
            blob, digest = webp_preview(source)
            client.upload_preview(row["id"], blob, digest)
            with connection_factory() as connection:
                connection.execute(
                    "INSERT INTO cloud_sync(post_id,preview_hash,preview_source_hash,last_synced) VALUES(?,?,?,?) "
                    "ON CONFLICT(post_id) DO UPDATE SET preview_hash=excluded.preview_hash,preview_source_hash=excluded.preview_source_hash,last_synced=excluded.last_synced",
                    (row["id"], digest, source_digest, utcnow()),
                )
            preview_count += 1
        except Exception as error:
            with connection_factory() as connection:
                connection.execute(
                    "INSERT INTO cloud_sync(post_id,last_error) VALUES(?,?) ON CONFLICT(post_id) DO UPDATE SET last_error=excluded.last_error",
                    (row["id"], str(error)[:1000]),
                )
    with connection_factory() as connection:
        connection.execute("INSERT OR REPLACE INTO sync_meta VALUES('cursor',?)", (str(next_cursor),))
        connection.execute("INSERT OR REPLACE INTO sync_meta VALUES('last_sync',?)", (utcnow(),))
    client.acknowledge(next_cursor)
    return {
        "configured": True,
        "status": "complete" if not response.get("conflicts") else "conflict",
        "pulled": len(pulled.get("mutations", [])),
        "pushed": len(accepted),
        "previews": preview_count,
        "conflicts": response.get("conflicts", []),
        "cursor": next_cursor,
    }
