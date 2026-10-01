"""Unit tests for the pure check functions. Run: python3 -m unittest discover -s tests"""
import importlib.machinery, importlib.util, os, unittest

path = os.path.join(os.path.dirname(__file__), "..", "frigate-watchdog")
loader = importlib.machinery.SourceFileLoader("fw", path)
fw = importlib.util.module_from_spec(importlib.util.spec_from_loader("fw", loader))
loader.exec_module(fw)


class Storage(unittest.TestCase):
    def test_flags_full_disk_once_per_device(self):
        stats = {"service": {"storage": {
            "/media/frigate/recordings": {"total": 1000.0, "used": 950.0},
            "/media/frigate/clips": {"total": 1000.0, "used": 950.0},   # same device, same numbers
            "/dev/shm": {"total": 1000.0, "used": 100.0}}}}
        out = fw.storage_problems(stats, 90)
        self.assertEqual(list(out), ["disk:/media/frigate/recordings"])

    def test_quiet_when_healthy_or_missing(self):
        self.assertEqual(fw.storage_problems({}, 90), {})
        self.assertEqual(fw.storage_problems({"service": {"storage": {"/x": {"total": 0, "used": 0}}}}, 90), {})


class Detector(unittest.TestCase):
    def test_idle_is_healthy(self):
        d = {"detectors": {"coral": {"pid": 5, "detection_start": 0.0, "inference_speed": 6.6}}}
        self.assertEqual(fw.detector_problems(d, 1000, 60, 0), {})

    def test_missing_process_stuck_and_slow(self):
        self.assertIn("detector:a", fw.detector_problems({"detectors": {"a": {"pid": None}}}, 1000, 60, 0))
        self.assertIn("detector:a", fw.detector_problems({"detectors": {"a": {"pid": 1, "detection_start": 900}}}, 1000, 60, 0))
        self.assertEqual(fw.detector_problems({"detectors": {"a": {"pid": 1, "detection_start": 990}}}, 1000, 60, 0), {})
        self.assertIn("detector:a", fw.detector_problems({"detectors": {"a": {"pid": 1, "inference_speed": 250.0}}}, 1000, 60, 100))
        self.assertEqual(fw.detector_problems({"detectors": {"a": {"pid": 1, "inference_speed": 250.0}}}, 1000, 60, 0), {})

    def test_skipped_frames_ignore_disabled_and_ignored(self):
        stats = {"cameras": {"a": {"skipped_fps": 2.0}, "b": {"skipped_fps": 2.0}, "c": {"skipped_fps": 2.0}, "d": {"skipped_fps": 0}}}
        cfg = {"cameras": {"a": {"enabled": True}, "b": {"enabled": False}, "c": {}, "d": {}}}
        self.assertEqual(sorted(fw.skipped_problems(stats, cfg, {"c"})), ["skipped:a"])


class Restarts(unittest.TestCase):
    def test_loop_detected_after_three_drops(self):
        st = {}
        out = fw.restart_problems(st, 5000, 1000, 3)               # first run: no history, no restart
        self.assertEqual(out, {})
        for i, up in enumerate([10, 70, 5, 65, 8], start=1):       # uptime falls twice, then a third time
            out = fw.restart_problems(st, up, 1000 + i * 60, 3)
        self.assertIn("restart-loop", out)

    def test_normal_uptime_growth_is_quiet(self):
        st = {}
        for i in range(10):
            self.assertEqual(fw.restart_problems(st, 100 + i * 60, 1000 + i * 60, 3), {})

    def test_old_restarts_expire(self):
        st = {"uptime": 9999, "restarts": [100, 200, 300]}
        self.assertEqual(fw.restart_problems(st, 10000, 100000, 3), {})


class LogScan(unittest.TestCase):
    LOG = (
        "x Fatal Python error: Bus error\n"
        + "x watchdog.cam1 ERROR : Ffmpeg process crashed unexpectedly for cam1.\n" * 3
        + "x watchdog.dead ERROR : Ffmpeg process crashed unexpectedly for dead.\n" * 4
        + "x ffmpeg.cam1.detect ERROR : Failed to sync surface 0x15\n" * 2
        + "x Non-monotonic DTS; previous\nx non monotonically increasing dts\n"
    )

    def test_scan_counts_and_ignore(self):
        hits = {(k, key): n for k, key, n in fw.scan_log_text(self.LOG, {"dead"})}
        self.assertEqual(hits[("crit", "fatal Python error")], 1)
        self.assertEqual(hits[("crit", "shared memory too small (bus error)")], 1)
        self.assertEqual(hits[("crash", "cam1")], 3)
        self.assertNotIn(("crash", "dead"), hits)
        self.assertEqual(hits[("rate", "GPU surface sync failures")], 2)
        self.assertEqual(hits[("rate", "non-monotonic timestamps")], 2)

    def test_problems_threshold_and_hold(self):
        st = {"loghist": [[1000, "crit", "disk full", 1], [1000, "rate", "GPU surface sync failures", 10],
                          [1000, "crash", "cam1", 40], [-3000, "crash", "old", 99]]}
        out = fw.log_problems(st, 1100, burst=30, crash_per_hour=30, hold=900)
        self.assertEqual(sorted(out), ["log:crash:cam1", "log:disk full"])      # sync burst below 30, 'old' expired
        out = fw.log_problems(st, 2100, burst=30, crash_per_hour=30, hold=900)  # past hold, still inside the hour
        self.assertEqual(sorted(out), ["log:crash:cam1"])

    def test_clean_log_is_quiet(self):
        self.assertEqual(fw.scan_log_text("INFO all good\n", set()), [])


if __name__ == "__main__":
    unittest.main()
