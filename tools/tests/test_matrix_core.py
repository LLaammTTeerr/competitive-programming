import unittest

from tools.matrix_core import Limits, classify, compute_limits


class TestComputeLimits(unittest.TestCase):
    def test_floor_binds_for_a_fast_model_solution(self):
        limits = compute_limits({"01": 8, "02": 5})
        self.assertEqual(limits.t_main_ms, 8)
        self.assertEqual(limits.tl_ms, 1000)
        self.assertEqual(limits.kill_ms, 2000)

    def test_uses_the_slowest_test_not_the_mean(self):
        self.assertEqual(compute_limits({"01": 10, "02": 900}).t_main_ms, 900)

    def test_doubles_and_rounds_up_to_the_step(self):
        # 900 -> 1800 -> rounded up to 2000
        limits = compute_limits({"01": 900})
        self.assertEqual(limits.tl_ms, 2000)
        self.assertEqual(limits.kill_ms, 4000)

    def test_spec_worked_example(self):
        # t_main 370 ms: 2x = 740, below the 1000 floor, so TL is 1000.
        limits = compute_limits({"01": 370})
        self.assertEqual(limits.tl_ms, 1000)
        self.assertEqual(limits.kill_ms, 2000)

    def test_rejects_an_empty_timing_table(self):
        with self.assertRaises(ValueError):
            compute_limits({})

    def test_rounding_boundary_500ms_gives_exactly_1000(self):
        # t_main = 500: 2*500 = 1000 (at floor), ceil(1000/500)*500 = 1000
        limits = compute_limits({"01": 500})
        self.assertEqual(limits.tl_ms, 1000)
        self.assertEqual(limits.kill_ms, 2000)

    def test_rounding_boundary_501ms_gives_1500(self):
        # t_main = 501: 2*501 = 1002, ceil(1002/500)*500 = 1500
        limits = compute_limits({"01": 501})
        self.assertEqual(limits.tl_ms, 1500)
        self.assertEqual(limits.kill_ms, 3000)

    def test_kill_ms_is_computed_from_rounded_tl_not_raw(self):
        # 900 -> 1800 (raw) -> 2000 (rounded TL) -> 4000 (kill from rounded)
        # If kill were computed from raw: 2*1800 = 3600 (wrong)
        limits = compute_limits({"01": 900})
        self.assertEqual(limits.kill_ms, 4000)
        self.assertNotEqual(limits.kill_ms, 3600)


LIMITS = Limits(t_main_ms=500, tl_ms=1000, kill_ms=2000)


class TestClassify(unittest.TestCase):
    def test_fast_and_correct_is_ok(self):
        out = classify(300, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "OK")
        self.assertFalse(out.banded)

    def test_fast_and_wrong_is_wa(self):
        self.assertEqual(
            classify(300, killed=False, checker_verdict="WA", limits=LIMITS).verdict,
            "WA")

    def test_killed_is_tl_and_not_banded(self):
        out = classify(2000, killed=True, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertFalse(out.banded)

    def test_over_the_limit_but_finished_is_banded_tl(self):
        out = classify(1400, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertTrue(out.banded)

    def test_time_beats_a_wrong_answer_when_over_the_limit(self):
        # A solution that is both slow and wrong is reported as TL: the judge
        # would have stopped it before the checker ever ran.
        out = classify(1400, killed=False, checker_verdict="WA", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")

    def test_exactly_at_the_limit_is_accepted(self):
        self.assertEqual(
            classify(1000, killed=False, checker_verdict="OK", limits=LIMITS).verdict,
            "OK")

    def test_checker_fail_surfaces_as_fail_not_wa(self):
        # inf/ans read failures are package bugs, never the solution's fault.
        self.assertEqual(
            classify(10, killed=False, checker_verdict="FAIL", limits=LIMITS).verdict,
            "FAIL")

    def test_presentation_error_is_preserved(self):
        self.assertEqual(
            classify(10, killed=False, checker_verdict="PE", limits=LIMITS).verdict,
            "PE")

    def test_one_ms_over_limit_is_banded(self):
        # time_ms = tl_ms + 1 should be banded TL
        out = classify(1001, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertTrue(out.banded)

    def test_at_kill_boundary_is_still_banded(self):
        # time_ms = kill_ms should still be banded
        out = classify(2000, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertTrue(out.banded)

    def test_beyond_kill_boundary_is_not_banded(self):
        # time_ms = kill_ms + 1 should be TL but not banded
        out = classify(2001, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertFalse(out.banded)

    def test_re_verdict_fast(self):
        # RE (Runtime Error) should be preserved for fast solutions
        out = classify(100, killed=False, checker_verdict="RE", limits=LIMITS)
        self.assertEqual(out.verdict, "RE")
        self.assertFalse(out.banded)


if __name__ == "__main__":
    unittest.main()
