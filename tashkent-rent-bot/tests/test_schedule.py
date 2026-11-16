from datetime import datetime, timedelta, timezone
import unittest

from rentbot.schedule import quiet_due


TZ = timezone(timedelta(hours=5))


class ScheduleTests(unittest.TestCase):
    def local(self, day, hour=0, minute=0, second=0, microsecond=0):
        return datetime(2026, 11, day, hour, minute, second, microsecond, tzinfo=TZ)

    def test_monday_morning_queues_until_1650(self):
        self.assertEqual(quiet_due(self.local(16, 8)), self.local(16, 16, 50))

    def test_one_microsecond_before_cutoff_queues(self):
        self.assertEqual(
            quiet_due(self.local(16, 16, 49, 59, 999999)), self.local(16, 16, 50)
        )

    def test_at_cutoff_and_after_immediate(self):
        for moment in (self.local(16, 16, 50), self.local(16, 23, 59)):
            with self.subTest(moment=moment):
                self.assertEqual(quiet_due(moment), moment)

    def test_friday_late_is_not_delayed_until_monday(self):
        moment = self.local(20, 19)
        self.assertEqual(quiet_due(moment), moment)

    def test_weekends_immediate_even_at_midnight(self):
        for day in (14, 15):
            for hour in (0, 8, 17, 23):
                moment = self.local(day, hour)
                self.assertEqual(quiet_due(moment), moment)

    def test_tashkent_weekday_used_even_when_utc_is_sunday(self):
        utc_sunday = datetime(2026, 11, 15, 22, tzinfo=timezone.utc)
        self.assertEqual(quiet_due(utc_sunday), self.local(16, 16, 50))

    def test_midnight_monday_starts_new_queue(self):
        self.assertEqual(quiet_due(self.local(16)), self.local(16, 16, 50))

    def test_result_always_utc(self):
        self.assertIs(quiet_due(self.local(16, 8)).tzinfo, timezone.utc)

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            quiet_due(datetime(2026, 11, 16, 8))


if __name__ == "__main__":
    unittest.main()
