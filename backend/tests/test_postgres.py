"""Integration tests against real PostgreSQL in a disposable schema."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from db.database import connect, database_url, initialize
from agent.personality import score_assessment
from agent.personality.assessment import ITEMS
from agent.personality.repository import latest_assessment, save_assessment, save_skipped

BASE_URL = os.getenv("TWINLOOP_TEST_DATABASE_URL")


def schema_url(url: str, schema: str) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    query["options"] = "-csearch_path=" + schema
    return urlunsplit(parsed._replace(query=urlencode(query)))


class ConfigurationTests(unittest.TestCase):
    def test_rejects_other_engines_and_paths_even_when_passed_explicitly(self):
        for value in ["sqlite:///forbidden.db", "file.db", "mysql://u@localhost/x", "postgresql://localhost", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                connect(value)

    def test_accepts_postgres_schemes(self):
        for value in ["postgres://u@localhost/x", "postgresql://u@localhost/x"]:
            self.assertEqual(database_url(value), value)


@unittest.skipUnless(BASE_URL, "Set TWINLOOP_TEST_DATABASE_URL to a disposable-test-capable PostgreSQL database")
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.schema = "test_twinloop_" + uuid4().hex
        with connect(BASE_URL) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.env = patch.dict(os.environ, {"DATABASE_URL": schema_url(BASE_URL, self.schema)})
        self.env.start()
        initialize()

    def tearDown(self):
        self.env.stop()
        self.assertTrue(self.schema.startswith("test_twinloop_"))
        with connect(BASE_URL) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def result(self):
        # Extremes align with keying: expected scores are exactly 10 in every dimension.
        return score_assessment({i.id: 1 if i.reverse else 5 for i in ITEMS},
                                "assessment_" + uuid4().hex, notes="私有备注：测试中文 JSONB")

    def test_repeat_and_concurrent_migrations_preserve_data(self):
        save_assessment("u1", self.result())
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(lambda _: initialize(), range(3))), [3, 3, 3])
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"], 3)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM personality_assessments").fetchone()["n"], 1)

    def test_changed_migration_is_rejected(self):
        with connect() as db:
            db.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=1")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            initialize()

    def test_failed_migration_rolls_back_ddl_and_metadata(self):
        from db import database
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "003_test.sql"
            migration.write_text("CREATE TABLE rollback_probe(id TEXT); SELECT 1/0;", encoding="utf-8")
            files = database.migration_files() + [(4, migration)]
            with patch.object(database, "migration_files", return_value=files):
                with self.assertRaises(psycopg.errors.DivisionByZero):
                    initialize()
        with connect() as db:
            self.assertIsNone(db.execute("SELECT to_regclass('rollback_probe') AS name").fetchone()["name"])
            self.assertEqual(db.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"], 3)

    def test_jsonb_roundtrip_and_read_in_another_process(self):
        result = self.result()
        self.assertEqual(save_assessment("u1", result), result)
        self.assertEqual(latest_assessment("u1"), result)
        self.assertIsNone(latest_assessment("someone_else"))
        with connect() as db:
            row = db.execute("SELECT result_json, skipped, created_at FROM personality_assessments").fetchone()
        self.assertIsInstance(row["result_json"], dict)
        self.assertIs(row["skipped"], False)
        self.assertIsNotNone(row["created_at"].tzinfo)
        code = "from agent.personality.repository import latest_assessment; assert latest_assessment('u1')['assessment_id'] == " + repr(result["assessment_id"])
        child = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_idempotency_and_concurrent_first_submissions(self):
        result = self.result()
        with ThreadPoolExecutor(max_workers=5) as pool:
            saved = list(pool.map(lambda _: save_assessment("u1", result, "same-request"), range(5)))
        self.assertTrue(all(value == result for value in saved))
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM avatars").fetchone()["n"], 1)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM personality_assessments").fetchone()["n"], 1)

    def test_skip_nulls_boolean_and_private_defaults(self):
        saved = save_skipped("u1", "skip1", "skip-request")
        self.assertEqual(latest_assessment("u1"), saved)
        self.assertTrue(all(value is None for value in saved["scores"].values()))
        self.assertEqual(save_skipped("u1", "skip2", "skip-request"), saved)
        with connect() as db:
            self.assertIs(db.execute("SELECT skipped FROM personality_assessments").fetchone()["skipped"], True)
            row = db.execute("""
                INSERT INTO memories(id, avatar_id, depth, memory_type, payload_json, created_at, updated_at)
                SELECT 'm1', id, 'middle', 'behavior', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM avatars RETURNING privacy, share
            """, (Jsonb({"reaction": "先确认条件"}),)).fetchone()
            self.assertEqual(row, {"privacy": "private", "share": False})

    def test_cascade_and_transaction_rollback(self):
        save_assessment("u1", self.result())
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with connect() as db:
                db.execute("INSERT INTO users VALUES ('rolled_back', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)")
                db.execute("""
                    INSERT INTO avatars(id, user_id, created_at, updated_at)
                    VALUES ('bad', 'nonexistent', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """)
        with connect() as db:
            self.assertIsNone(db.execute("SELECT id FROM users WHERE id='rolled_back'").fetchone())
            db.execute("DELETE FROM users WHERE id='u1'")
            self.assertEqual(db.execute("SELECT count(*) AS n FROM personality_assessments").fetchone()["n"], 0)
        self.assertIsNone(latest_assessment("u1"))

    def test_api_submission_and_card_projection_use_postgres(self):
        from fastapi.testclient import TestClient
        from app.main import app, profiles, versions
        user = "api_" + uuid4().hex
        headers = {"X-User-Id": user}
        try:
            with TestClient(app) as client:
                questions = client.get("/v1/personality/questions").json()
                self.assertEqual(len(questions["items"]), 50)
                response = client.post("/v1/personality/assessments", headers=headers,
                    json={"answers": self.result()["raw_answers"], "request_key": "api"})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(latest_assessment(user), result)
                profile = client.get("/v1/twin/profile", headers=headers).json()
                response = client.post("/v1/twin/versions", headers=headers,
                    json={"expected_revision": profile["revision"]})
                self.assertEqual(response.status_code, 201, response.text)
                card = response.json()["card"]
                self.assertIsInstance(card["data"]["personality"], str)
                exported = card["data"]["extensions"]["twin"]["personality"]
                self.assertEqual(exported["scores"], result["scores"])
                self.assertNotIn("raw_answers", exported)
                self.assertEqual(client.get("/v1/personality/assessments/latest",
                    headers={"X-User-Id": "other"}).status_code, 404)
        finally:
            profiles.pop(user, None)
            for vid in [key for key, value in versions.items() if value["user_id"] == user]:
                versions.pop(vid)


if __name__ == "__main__":
    unittest.main()
