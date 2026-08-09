import errno
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tools import box_pool


class BoxPoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="box_pool_test_"))
        self._env = {}
        self._set("RUN_MATRIX_BOX_LOCK_DIR", str(self.tmp))
        self._set("RUN_MATRIX_BOX_POOL", "2")

    def tearDown(self):
        for key, old in self._env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def _set(self, key, value):
        self._env.setdefault(key, os.environ.get(key))
        os.environ[key] = value

    def test_pool_size_reads_the_environment_override(self):
        self._set("RUN_MATRIX_BOX_POOL", "5")
        self.assertEqual(box_pool.pool_size(), 5)

    def test_pool_size_defaults_to_half_the_cpus_and_is_at_least_one(self):
        os.environ.pop("RUN_MATRIX_BOX_POOL", None)
        expected = max(1, (os.cpu_count() or 2) // 2)
        self.assertEqual(box_pool.pool_size(), expected)

    def test_pool_size_rejects_a_nonsense_override(self):
        self._set("RUN_MATRIX_BOX_POOL", "0")
        with self.assertRaises(box_pool.BoxPoolError):
            box_pool.pool_size()

    def test_pool_size_rejects_a_non_integer_override(self):
        self._set("RUN_MATRIX_BOX_POOL", "many")
        with self.assertRaises(box_pool.BoxPoolError):
            box_pool.pool_size()

    def test_pool_size_rejects_an_override_above_the_isolate_box_id_range(self):
        self._set("RUN_MATRIX_BOX_POOL", "65537")
        with self.assertRaises(box_pool.BoxPoolError) as ctx:
            box_pool.pool_size()
        self.assertIn("65536", str(ctx.exception))

    def test_pool_size_accepts_the_maximum_isolate_box_id_count(self):
        self._set("RUN_MATRIX_BOX_POOL", "65536")
        self.assertEqual(box_pool.pool_size(), 65536)

    def test_default_lock_dir_is_scoped_to_the_current_uid(self):
        # Pure computation, no filesystem writes: _default_lock_dir() only
        # stats /run/user/<uid>, it never creates anything, so this is safe
        # to call even though $RUN_MATRIX_BOX_LOCK_DIR is set in setUp (that
        # env var is irrelevant to this helper -- lock_dir() is the one that
        # consults it).
        path = box_pool._default_lock_dir()
        self.assertIn(str(os.getuid()), str(path))
        self.assertTrue(
            str(path).startswith("/run/user/") or str(path).startswith("/tmp/"),
            f"unexpected default lock dir: {path}",
        )

    def test_default_lock_dir_falls_back_to_a_uid_suffixed_tmp_dir(self):
        # When the per-user runtime dir isn't usable (no systemd, wrong
        # permissions, doesn't exist yet), the fallback must still be
        # scoped per-user -- otherwise two users sharing /tmp would collide
        # on the same lock directory, exactly what the per-user ruling
        # rules out. Still pure computation: mocking os.access means this
        # never calls mkdir.
        with mock.patch.object(box_pool.os, "access", return_value=False):
            path = box_pool._default_lock_dir()
        self.assertEqual(path, Path(f"/tmp/run_matrix-boxes-{os.getuid()}"))

    def test_lease_yields_an_id_inside_the_pool(self):
        with box_pool.lease(timeout_s=5.0) as box_id:
            self.assertIn(box_id, range(2))

    def test_two_concurrent_leases_never_return_the_same_id(self):
        with box_pool.lease(timeout_s=5.0) as a, box_pool.lease(timeout_s=5.0) as b:
            self.assertNotEqual(a, b)

    def test_lease_is_released_on_exit_and_the_id_is_reusable(self):
        with box_pool.lease(timeout_s=5.0) as a:
            first = a
        with box_pool.lease(timeout_s=5.0) as b:
            self.assertEqual(first, b)

    def test_lease_is_released_when_the_body_raises(self):
        with self.assertRaises(ValueError):
            with box_pool.lease(timeout_s=5.0):
                raise ValueError("boom")
        with box_pool.lease(timeout_s=5.0) as a, box_pool.lease(timeout_s=5.0) as b:
            self.assertEqual({a, b}, {0, 1})

    def test_exhausted_pool_raises_rather_than_hanging_forever(self):
        with box_pool.lease(timeout_s=5.0), box_pool.lease(timeout_s=5.0):
            with self.assertRaises(box_pool.BoxPoolError) as ctx:
                with box_pool.lease(timeout_s=0.5):
                    self.fail("a third lease was granted from a pool of two")
        self.assertIn("RUN_MATRIX_BOX_POOL", str(ctx.exception))

    def test_a_waiting_lease_is_granted_once_a_holder_releases(self):
        granted = []

        def waiter():
            with box_pool.lease(timeout_s=30.0) as box_id:
                granted.append(box_id)

        with box_pool.lease(timeout_s=5.0) as first:
            inner = box_pool.lease(timeout_s=5.0)
            inner.__enter__()                 # pool of two is now exhausted
            thread = threading.Thread(target=waiter)
            thread.start()
            thread.join(timeout=1.0)
            self.assertTrue(thread.is_alive(), "waiter should still be blocked")
            inner.__exit__(None, None, None)  # release the second lease
            thread.join(timeout=30.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(granted), 1)
        self.assertNotEqual(granted[0], first)

    def test_a_lease_held_by_another_process_is_not_handed_out_here(self):
        # A separate process, not a thread: flock is per open file description,
        # and the whole point of this pool is cross-invocation exclusion.
        #
        # This test used to compare a single id from each side and only
        # caught a totally broken flock() about half the time (with a pool
        # of 2, an unlocked process falls back to a bare pid % 2, which
        # coincidentally differs from the other process's id half the
        # time). To make it deterministic: the child holds every id but
        # one, so a correct sweep here is *forced* to land on the single
        # remaining free id -- there is no other id it could correctly
        # return -- and once we hold that one too, the pool is completely
        # exhausted between the two processes, so one more lease attempt
        # must time out. A broken lock hands out *some* id on its very
        # first try regardless of what's already held, so both assertions
        # fail unconditionally under that failure, not by chance.
        pool_size = 4
        self._set("RUN_MATRIX_BOX_POOL", str(pool_size))
        script = (
            "import sys,time,contextlib\n"
            "sys.path.insert(0, %r)\n"
            "from tools import box_pool\n"
            "with contextlib.ExitStack() as stack:\n"
            "    ids = [stack.enter_context(box_pool.lease(timeout_s=30.0)) for _ in range(%d)]\n"
            "    print(','.join(map(str, ids)), flush=True)\n"
            "    time.sleep(30)\n"
        ) % (str(Path(__file__).resolve().parents[2]), pool_size - 1)
        child = subprocess.Popen([sys.executable, "-c", script],
                                 stdout=subprocess.PIPE, text=True,
                                 env={**os.environ})
        try:
            theirs = {int(x) for x in child.stdout.readline().strip().split(",")}
            self.assertEqual(
                len(theirs), pool_size - 1,
                "the child should hold every id but one",
            )
            free = (set(range(pool_size)) - theirs).pop()
            with box_pool.lease(timeout_s=5.0) as ours:
                self.assertEqual(ours, free)
                with self.assertRaises(box_pool.BoxPoolError):
                    with box_pool.lease(timeout_s=0.5):
                        self.fail(
                            "a lease was granted while the pool was fully "
                            "held by this process and another"
                        )
        finally:
            child.stdout.close()
            child.kill()
            child.wait(timeout=10)

    def test_a_lease_is_released_when_its_holder_process_dies(self):
        # Pool of one: the only id there is must become leasable again once
        # its sole holder dies. A short explicit timeout_s means a
        # regression here fails fast (BoxPoolError) instead of hanging the
        # whole suite behind the default 3600s.
        self._set("RUN_MATRIX_BOX_POOL", "1")
        script = (
            "import sys,time\n"
            "sys.path.insert(0, %r)\n"
            "from tools import box_pool\n"
            "with box_pool.lease(timeout_s=30.0) as b:\n"
            "    print(b, flush=True)\n"
            "    time.sleep(30)\n"
        ) % str(Path(__file__).resolve().parents[2])
        child = subprocess.Popen([sys.executable, "-c", script],
                                 stdout=subprocess.PIPE, text=True)
        try:
            theirs = int(child.stdout.readline().strip())
            child.kill()
            child.wait(timeout=10)
            with box_pool.lease(timeout_s=5.0) as reclaimed:
                self.assertEqual(reclaimed, theirs)
        finally:
            child.stdout.close()
            child.kill()
            child.wait(timeout=10)

    def test_lease_wraps_an_unopenable_lock_file_in_box_pool_error(self):
        if hasattr(os, "getuid") and os.getuid() == 0:
            self.skipTest("root bypasses directory permission bits")
        box_pool.lock_dir()          # create the directory first
        os.chmod(self.tmp, 0o500)    # r-x: no new files can be opened inside
        try:
            with self.assertRaises(box_pool.BoxPoolError) as ctx:
                with box_pool.lease(timeout_s=5.0):
                    self.fail("a lease was granted from an unwritable lock dir")
            self.assertIn("cannot open the box-lease file", str(ctx.exception))
        finally:
            os.chmod(self.tmp, 0o700)

    def test_lease_wraps_a_non_blocking_lock_failure_in_box_pool_error(self):
        with mock.patch(
            "tools.box_pool.fcntl.flock",
            side_effect=OSError(errno.EIO, "Input/output error"),
        ):
            with self.assertRaises(box_pool.BoxPoolError) as ctx:
                with box_pool.lease(timeout_s=5.0):
                    self.fail("a lease was granted despite a broken flock() call")
        self.assertIn("cannot lock the box-lease file", str(ctx.exception))

    def test_lock_dir_reports_an_uncreatable_directory_as_box_pool_error(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("not a directory")
        self._set("RUN_MATRIX_BOX_LOCK_DIR", str(blocker / "boxes"))
        with self.assertRaises(box_pool.BoxPoolError) as ctx:
            box_pool.lock_dir()
        self.assertIn("cannot create the box-lease directory", str(ctx.exception))
