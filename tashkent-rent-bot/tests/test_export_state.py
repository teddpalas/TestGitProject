import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from deployment.export_state import export
from rentbot.service import single_instance
from rentbot.storage import Store


class ExportStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(contextlib.chdir(self.root))
        self.context.enter_context(patch.dict(os.environ, {}, clear=True))
        self.data = self.root / "data"
        self.data.mkdir()
        self.environment = (
            "# Private example; all credentials below are fake.\r\n"
            "TELEGRAM_API_ID=12345\r\n"
            "TELEGRAM_API_HASH=" + "a" * 32 + "\r\n"
            "TELEGRAM_BOT_TOKEN=123456:" + "x" * 30 + "\r\n"
            "TELEGRAM_CHAT_ID=222222\r\n"
            "DATA_DIR=data\r\nLOCATIONS_FILE=locations.json\r\n"
            "ROUTING_PROVIDER=geoapify\r\nGEOAPIFY_API_KEY=fake-geoapify-key\r\n"
        ).encode("utf-8")
        (self.root / ".env").write_bytes(self.environment)
        (self.root / "locations.json").write_text("[]", encoding="utf-8")
        self.session = sqlite3.connect(self.data / "reader.session")
        self.context.callback(self.session.close)
        self.session.execute("PRAGMA journal_mode=WAL")
        self.session.execute("CREATE TABLE account (reader_id INTEGER, auth_key BLOB)")
        self.session.execute("INSERT INTO account VALUES (?, ?)", (111111, b"fake-session-key"))
        self.session.commit()
        self.store = Store(self.data / "rentbot.sqlite3")
        self.context.callback(self.store.close)
        self.store.set_meta("cursor:Apartament_999", "457")
        self.store.set_meta("updates_offset", "812")
        self.store.set_meta("paused", "true")
        self.now = datetime(2026, 1, 12, 12, tzinfo=timezone.utc)
        self.store.enqueue("queued", "revision-1", "quiet", {"text": "Synthetic listing"}, self.now)
        self.store.enqueue("delivered", "revision-2", "loud", {}, self.now)
        self.store.mark_sent("delivered", "revision-2")
        self.output = self.data / "oci/private-state.tar.gz"

    def test_busy_instance_lock_refuses_export_without_creating_archive(self):
        with single_instance(self.data / "run.lock"):
            with self.assertRaises(RuntimeError):
                export(self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual((self.root / ".env").read_bytes(), self.environment)
        self.assertEqual(self.store.counts()["pending"], 1)

    def test_export_preserves_committed_wal_session_queue_and_recipient(self):
        self.assertGreater((self.data / "reader.session-wal").stat().st_size, 0)
        self.assertGreater((self.data / "rentbot.sqlite3-wal").stat().st_size, 0)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            export(self.output)
        self.assertNotIn("fake-geoapify-key", output.getvalue())
        with tarfile.open(self.output, "r:gz") as archive:
            self.assertEqual(set(archive.getnames()), {
                ".env", "migration.json", "data/reader.session", "data/rentbot.sqlite3",
                "data/locations.json",
            })
            self.assertEqual(archive.extractfile(".env").read(), self.environment)
            self.assertEqual(json.load(archive.extractfile("migration.json"))["format_version"], 1)
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual(member.mode, 0o600)
                self.assertEqual((member.uid, member.gid), (0, 0))
            for name in ("reader.session", "rentbot.sqlite3"):
                (self.root / ("snapshot-" + name)).write_bytes(archive.extractfile("data/" + name).read())
        with contextlib.closing(sqlite3.connect(self.root / "snapshot-reader.session")) as snapshot:
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(snapshot.execute("SELECT reader_id, auth_key FROM account").fetchone(),
                             (111111, b"fake-session-key"))
        with Store(self.root / "snapshot-rentbot.sqlite3") as snapshot:
            self.assertEqual(snapshot.get_meta("cursor:Apartament_999"), "457")
            self.assertEqual(snapshot.get_meta("updates_offset"), "812")
            self.assertEqual(snapshot.get_meta("paused"), "true")
            self.assertEqual(snapshot.counts(), self.store.counts())
            self.assertEqual(snapshot.due(self.now), self.store.due(self.now))
        self.assertEqual((self.root / ".env").read_bytes(), self.environment)

    def test_existing_private_archive_is_not_overwritten(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b"previous-private-backup")
        with self.assertRaises(FileExistsError):
            export(self.output)
        self.assertEqual(self.output.read_bytes(), b"previous-private-backup")


if __name__ == "__main__":
    unittest.main()
