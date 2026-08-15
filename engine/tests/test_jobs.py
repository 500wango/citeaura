import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import jobs as J


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_dir = J.JOBS_DIR
        J.JOBS_DIR = Path(self.tmp.name) / ".jobs"
        self.addCleanup(setattr, J, "JOBS_DIR", self._orig_dir)
        J._running.clear()
        J._procs.clear()
        self.addCleanup(J._running.clear)
        self.addCleanup(J._procs.clear)

    def _write_job(self, job_id, **kw):
        job = {"id": job_id, "slug": "x", "action": "audit", "label": "页面体检",
               "status": "running", "started_at": "2026-07-28T10:00:00",
               "finished_at": None, "exit_code": None}
        job.update(kw)
        J.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (J.JOBS_DIR / f"{job_id}.json").write_text(json.dumps(job), "utf-8")
        return job

    def test_reap_orphans_dead_pid(self):
        self._write_job("deadjob12345", pid=999999)
        with mock.patch.object(J.os, "kill", side_effect=ProcessLookupError):
            n = J.reap_orphans()
        self.assertEqual(n, 1)
        j = J.get("deadjob12345")
        self.assertEqual(j["status"], "interrupted")
        self.assertTrue(j["finished_at"])

    def test_reap_orphans_live_pid_untouched(self):
        self._write_job("livejob12345", pid=os.getpid())
        n = J.reap_orphans()
        self.assertEqual(n, 0)
        self.assertEqual(J.get("livejob12345")["status"], "running")

    def test_reap_orphans_skips_non_running(self):
        self._write_job("donejob123456", status="done", pid=999999)
        with mock.patch.object(J.os, "kill", side_effect=ProcessLookupError):
            n = J.reap_orphans()
        self.assertEqual(n, 0)
        self.assertEqual(J.get("donejob123456")["status"], "done")

    def test_start_popen_failure_marks_failed(self):
        with mock.patch.object(J.subprocess, "Popen", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                J.start("x", "audit")
        jobs = list(J.JOBS_DIR.glob("*.json"))
        self.assertEqual(len(jobs), 1)
        j = json.loads(jobs[0].read_text("utf-8"))
        self.assertEqual(j["status"], "failed")
        self.assertIn("boom", j["error"])
        self.assertTrue(j["finished_at"])
        self.assertNotIn(j["id"], J._procs)
        self.assertNotIn("x", J._running)

    def test_start_metadata_failure_releases_project_claim(self):
        with mock.patch.object(J, "_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                J.start("x", "audit")
        self.assertFalse((J.JOBS_DIR / "claims" / "x.json").exists())

    def test_start_writes_pid(self):
        proc = mock.Mock()
        proc.pid = 424242
        proc.wait.return_value = 0
        with mock.patch.object(J.subprocess, "Popen", return_value=proc):
            job = J.start("x", "audit")
        j = J.get(job["id"])
        self.assertEqual(j["pid"], 424242)

    def test_concurrent_start_uses_atomic_project_claim(self):
        release = threading.Event()
        proc = mock.Mock()
        proc.pid = 424243

        def wait():
            release.wait(2)
            return 0

        proc.wait.side_effect = wait
        with mock.patch.object(J.subprocess, "Popen", return_value=proc):
            first = J.start("x", "audit")
            with self.assertRaises(RuntimeError):
                J.start("x", "audit")
            release.set()
            for _ in range(50):
                if J.get(first["id"])["status"] != "running":
                    break
                time.sleep(0.01)

    def test_stop_fallback_by_pid(self):
        self._write_job("orphan1234567", pid=31337)
        with mock.patch.object(J.os, "getpgid", return_value=31337) as g, \
             mock.patch.object(J.os, "killpg") as k, \
             mock.patch.object(J.os, "kill", side_effect=ProcessLookupError):
            ok = J.stop("orphan1234567")
        self.assertTrue(ok)
        g.assert_called_once_with(31337)
        k.assert_called_once()
        j = J.get("orphan1234567")
        self.assertEqual(j["status"], "stopped")
        self.assertTrue(j["finished_at"])

    def test_stop_fallback_rejects_reused_non_leader_pid(self):
        self._write_job("reusedpid123", pid=31336)
        with mock.patch.object(J.os, "getpgid", return_value=99999), \
             mock.patch.object(J.os, "killpg") as killpg:
            self.assertFalse(J.stop("reusedpid123"))
        killpg.assert_not_called()

    def test_stop_waits_for_in_memory_process(self):
        self._write_job("active1234567", pid=31338)
        proc = mock.Mock(pid=31338)
        proc.wait.return_value = -signal.SIGTERM
        J._procs["active1234567"] = proc
        with mock.patch.object(J.os, "getpgid", return_value=31338), \
             mock.patch.object(J.os, "killpg") as killpg:
            self.assertTrue(J.stop("active1234567"))
        killpg.assert_called_once_with(31338, signal.SIGTERM)
        proc.wait.assert_called_once_with(timeout=J.STOP_GRACE_SECONDS)
        self.assertEqual(J.get("active1234567")["status"], "stopped")

    def test_stop_request_remains_stopped_after_graceful_zero_exit(self):
        self._write_job("graceful12345", pid=31341)
        proc = mock.Mock(pid=31341)
        proc.wait.return_value = 0
        J._procs["graceful12345"] = proc
        with mock.patch.object(J.os, "getpgid", return_value=31341), \
             mock.patch.object(J.os, "killpg"):
            self.assertTrue(J.stop("graceful12345"))
        self.assertEqual(J.get("graceful12345")["status"], "stopped")

    def test_stop_escalates_after_grace_period(self):
        self._write_job("stubborn12345", pid=31339)
        proc = mock.Mock(pid=31339)
        proc.wait.side_effect = [subprocess.TimeoutExpired("geo", 5), -signal.SIGKILL]
        J._procs["stubborn12345"] = proc
        with mock.patch.object(J.os, "getpgid", return_value=31339), \
             mock.patch.object(J.os, "killpg") as killpg:
            self.assertTrue(J.stop("stubborn12345"))
        self.assertEqual(killpg.call_args_list, [
            mock.call(31339, signal.SIGTERM), mock.call(31339, signal.SIGKILL),
        ])
        self.assertEqual(J.get("stubborn12345")["exit_code"], -signal.SIGKILL)

    def test_stop_fallback_records_sigkill_escalation(self):
        self._write_job("orphanstubborn", pid=31340)
        with mock.patch.object(J, "STOP_GRACE_SECONDS", 0), \
             mock.patch.object(J, "STOP_KILL_SECONDS", 1), \
             mock.patch.object(J.os, "getpgid", return_value=31340), \
             mock.patch.object(J.os, "killpg") as killpg, \
             mock.patch.object(J.os, "kill", side_effect=ProcessLookupError):
            self.assertTrue(J.stop("orphanstubborn"))
        self.assertEqual(killpg.call_args_list, [
            mock.call(31340, signal.SIGTERM), mock.call(31340, signal.SIGKILL),
        ])
        self.assertEqual(J.get("orphanstubborn")["exit_code"], -signal.SIGKILL)

    def test_reap_skips_young_job_without_pid(self):
        self._write_job("youngjob12345")  # 刚落盘、还没来得及补 pid
        self.assertEqual(J.reap_orphans(), 0)
        self.assertEqual(J.get("youngjob12345")["status"], "running")

    def test_reap_old_job_without_pid(self):
        p = J.JOBS_DIR / "oldjob1234567.json"
        self._write_job("oldjob1234567")
        old = 1700000000  # 2023 年，远超 60s 窗口
        os.utime(p, (old, old))
        self.assertEqual(J.reap_orphans(), 1)
        self.assertEqual(J.get("oldjob1234567")["status"], "interrupted")

    def test_stop_unknown_job(self):
        self.assertFalse(J.stop("nosuchjob000"))

    def test_get_corrupt_json_returns_none(self):
        J.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (J.JOBS_DIR / "badjob123456.json").write_text("{not json", "utf-8")
        self.assertIsNone(J.get("badjob123456"))

    def test_job_ids_and_log_offsets_are_confined(self):
        self.assertIsNone(J.get("../../outside"))
        with self.assertRaises(ValueError):
            J.tail("../../outside")
        with self.assertRaises(ValueError):
            J.tail("valid-job", -1)


if __name__ == "__main__":
    unittest.main()
