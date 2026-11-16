from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from rentbot.storage import Store


NOW = datetime(2026, 11, 16, 11, 50, tzinfo=timezone.utc)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def queue(self, key="property", revision="v1", tier="quiet", due=NOW):
        return self.store.enqueue(key, revision, tier, {"text": "Квартира", "ids": [1, 2]}, due)

    def test_metadata_and_defaults(self):
        self.assertIsNone(self.store.get_meta("absent"))
        self.assertEqual(self.store.get_meta("absent", "0"), "0")
        self.store.set_meta("cursor", "123")
        self.store.set_meta("cursor", "124")
        self.assertEqual(self.store.get_meta("cursor"), "124")

    def test_new_item_and_payload_round_trip(self):
        self.assertTrue(self.queue())
        item = self.store.due(NOW)[0]
        self.assertEqual(item["payload"], {"text": "Квартира", "ids": [1, 2]})
        self.assertEqual(item["attempts"], 0)

    def test_no_early_delivery(self):
        self.queue(due=NOW + timedelta(hours=1))
        self.assertEqual(self.store.due(NOW), [])

    def test_duplicate_does_not_reset_retry_or_payload(self):
        self.queue()
        later = NOW + timedelta(minutes=5)
        self.store.retry("property", "v1", later, "temporary failure")
        self.assertFalse(self.queue())
        self.assertEqual(self.store.due(NOW), [])
        self.assertEqual(self.store.due(later)[0]["attempts"], 1)

    def test_updated_pending_revision_replaces_old(self):
        self.queue()
        self.queue(revision="v2")
        self.assertEqual([item["revision"] for item in self.store.due(NOW)], ["v2"])

    def test_quiet_to_loud_promotes_immediately(self):
        self.queue(due=NOW + timedelta(hours=2))
        self.assertTrue(self.queue(revision="v2", tier="loud"))
        self.assertEqual(self.store.due(NOW)[0]["tier"], "loud")

    def test_sent_quiet_can_become_loud(self):
        self.queue()
        self.store.mark_sent("property", "v1")
        self.assertTrue(self.queue(revision="v2", tier="loud"))

    def test_no_repeat_of_sent_revision(self):
        self.queue()
        self.store.mark_sent("property", "v1")
        self.assertFalse(self.queue())
        self.assertEqual(self.store.due(NOW), [])

    def test_sent_old_revision_cannot_reappear_after_new_revision(self):
        self.queue()
        self.store.mark_sent("property", "v1")
        self.queue(revision="v2")
        self.assertFalse(self.queue(revision="v1"))
        self.assertEqual(self.store.due(NOW)[0]["revision"], "v2")

    def test_first_loud_suppresses_all_future_notifications_for_key(self):
        self.queue(tier="loud")
        self.store.mark_sent("property", "v1")
        self.assertFalse(self.queue(revision="v2", tier="quiet"))
        self.assertFalse(self.queue(revision="v3", tier="loud"))

    def test_rejected_edit_cancels_waiting_item(self):
        self.queue()
        self.store.reject("property", "v2")
        self.assertEqual(self.store.due(NOW), [])
        self.assertFalse(self.queue(revision="v2"))
        self.assertEqual(self.store.counts()["rejected"], 1)

    def test_new_edit_after_rejection_can_qualify(self):
        self.store.reject("property", "v1")
        self.assertTrue(self.queue(revision="v2"))

    def test_stale_mark_sent_does_not_erase_new_revision(self):
        self.queue()
        self.queue(revision="v2")
        self.store.mark_sent("property", "v1")
        self.assertEqual(self.store.due(NOW)[0]["revision"], "v2")
        self.assertEqual(self.store.counts()["quiet_sent"], 1)

    def test_stale_loud_delivery_is_recorded_and_suppresses_extra_send(self):
        self.queue(tier="loud")
        self.queue(revision="v2", tier="loud")
        self.store.mark_sent("property", "v1")
        self.assertEqual(self.store.due(NOW), [])
        self.assertEqual(self.store.counts()["pending"], 0)

    def test_stale_retry_cannot_postpone_new_revision(self):
        self.queue()
        self.queue(revision="v2")
        self.store.retry("property", "v1", NOW + timedelta(hours=1), "old failure")
        self.assertEqual(self.store.due(NOW)[0]["revision"], "v2")
        self.assertEqual(self.store.due(NOW)[0]["attempts"], 0)

    def test_loud_prioritized_and_limit_applied(self):
        self.queue(key="quiet-first", due=NOW - timedelta(minutes=1))
        self.queue(key="loud-second", tier="loud")
        items = self.store.due(NOW, limit=1)
        self.assertEqual([item["key"] for item in items], ["loud-second"])

    def test_counts_track_delivery_history(self):
        self.queue(key="a")
        self.store.mark_sent("a", "v1")
        self.store.mark_sent("a", "v1")
        self.queue(key="b", tier="loud")
        self.store.mark_sent("b", "v1")
        self.queue(key="c")
        self.store.reject("d", "v1")
        self.assertEqual(self.store.counts(), {
            "pending": 1, "sent": 2, "quiet_sent": 1, "loud_sent": 1, "rejected": 1,
        })

    def test_unknown_mark_sent_is_noop(self):
        self.store.mark_sent("missing", "missing")
        self.assertEqual(self.store.counts()["sent"], 0)

    def test_naive_dates_and_invalid_tiers_fail_fast(self):
        with self.assertRaises(ValueError):
            self.queue(due=NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            self.store.due(NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            self.queue(tier="reject")
        with self.assertRaises(ValueError):
            self.store.due(NOW, limit=-1)

    def test_database_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.sqlite3"
            with Store(path) as first:
                first.set_meta("cursor", "10")
                first.enqueue("a", "1", "quiet", {"text": "Тест"}, NOW)
                first.enqueue("b", "1", "loud", {}, NOW)
                first.mark_sent("b", "1")
            with Store(path) as second:
                self.assertEqual(second.get_meta("cursor"), "10")
                self.assertEqual(second.due(NOW)[0]["key"], "a")
                self.assertFalse(second.enqueue("b", "2", "loud", {}, NOW))


if __name__ == "__main__":
    unittest.main()
