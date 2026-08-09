import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

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
        self.assertGreaterEqual(box_pool.pool_size(), 1)

    def test_pool_size_rejects_a_nonsense_override(self):
        self._set("RUN_MATRIX_BOX_POOL", "0")
        with self.assertRaises(box_pool.BoxPoolError):
            box_pool.pool_size()

    def test_lease_yields_an_id_inside_the_pool(self):
        with box_pool.lease() as box_id:
            self.assertIn(box_id, range(2))

    def test_two_concurrent_leases_never_return_the_same_id(self):
        with box_pool.lease() as a, box_pool.lease() as b:
            self.assertNotEqual(a, b)

    def test_lease_is_released_on_exit_and_the_id_is_reusable(self):
        with box_pool.lease() as a:
            first = a
        with box_pool.lease() as b:
            self.assertEqual(first, b)

    def test_lease_is_released_when_the_body_raises(self):
        with self.assertRaises(ValueError):
            with box_pool.lease():
                raise ValueError("boom")
        with box_pool.lease() as a, box_pool.lease() as b:
            self.assertEqual({a, b}, {0, 1})

    def test_exhausted_pool_raises_rather_than_hanging_forever(self):
        with box_pool.lease(), box_pool.lease():
            with self.assertRaises(box_pool.BoxPoolError) as ctx:
                with box_pool.lease(timeout_s=0.5):
                    self.fail("a third lease was granted from a pool of two")
        self.assertIn("RUN_MATRIX_BOX_POOL", str(ctx.exception))

    def test_a_waiting_lease_is_granted_once_a_holder_releases(self):
        granted = []

        def waiter():
            with box_pool.lease(timeout_s=30.0) as box_id:
                granted.append(box_id)

        with box_pool.lease() as first:
            inner = box_pool.lease()
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
        script = (
            "import os,sys,time\n"
            "sys.path.insert(0, %r)\n"
            "from tools import box_pool\n"
            "with box_pool.lease() as b:\n"
            "    print(b, flush=True)\n"
            "    time.sleep(30)\n"
        ) % str(Path(__file__).resolve().parents[2])
        child = subprocess.Popen([sys.executable, "-c", script],
                                 stdout=subprocess.PIPE, text=True,
                                 env={**os.environ})
        try:
            theirs = int(child.stdout.readline().strip())
            with box_pool.lease() as ours:
                self.assertNotEqual(ours, theirs)
        finally:
            child.kill()
            child.wait(timeout=10)

    def test_a_lease_is_released_when_its_holder_process_dies(self):
        script = (
            "import sys,time\n"
            "sys.path.insert(0, %r)\n"
            "from tools import box_pool\n"
            "with box_pool.lease() as b:\n"
            "    print(b, flush=True)\n"
            "    time.sleep(30)\n"
        ) % str(Path(__file__).resolve().parents[2])
        child = subprocess.Popen([sys.executable, "-c", script],
                                 stdout=subprocess.PIPE, text=True)
        theirs = int(child.stdout.readline().strip())
        child.kill()
        child.wait(timeout=10)
        with box_pool.lease() as a, box_pool.lease() as b:
            self.assertIn(theirs, {a, b})
