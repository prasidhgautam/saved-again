import json
import sqlite3
from pathlib import Path

import pytest

from backend.cloud_sync import assert_private_fields_absent, safe_projection


class Row(dict):
    def keys(self): return super().keys()


def test_safe_projection_excludes_local_evidence():
    row = Row(id="Synthetic001", position=2, updated="2026-11-12T00:00:00+00:00", revision=3,
              favourite=1, tried=0, dismissed=0, snoozed_until=None, notes="Keep", manual_category=1)
    data = {"id": "Synthetic001", "title": "Safe title", "summary": "Safe summary", "caption": "private raw caption", "transcript": "private transcript", "category": "learning", "subcategory": "Ideas"}
    projection = safe_projection(row, data)
    assert projection["title"] == "Safe title"
    assert "caption" not in projection and "transcript" not in projection
    assert projection["manual_category"] == 1


@pytest.mark.parametrize("payload", [
    {"transcript": "private"}, {"analysis": {"ocr_text": "private"}}, {"embeddings": [0.1]}, {"source_path": "/private/reel.mp4"},
])
def test_privacy_guard_rejects_raw_analysis(payload):
    with pytest.raises(ValueError, match="Private field"):
        assert_private_fields_absent(payload)


def test_cloudflare_migration_builds_required_d1_tables():
    migration = Path(__file__).resolve().parents[2] / "cloudflare" / "migrations" / "0001_initial.sql"
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(migration.read_text())
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"posts", "categories", "mutations", "sync_clients", "sync_requests"} <= tables
        assert connection.execute("SELECT count(*) FROM categories").fetchone()[0] == 11
