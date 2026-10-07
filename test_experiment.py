"""Tests for the stale-completion model. Expectations come from expected.json, which was
written and hashed before experiment.py existed; the property tests below check rules that
must hold across every trace, not just the named cases. Run:
  python3 -m unittest discover -p 'test_*.py' -v
"""
import hashlib
import json
import unittest
from pathlib import Path

import experiment as X

HERE = Path(__file__).parent
FIX = json.loads((HERE / "fixtures.json").read_text())
EXP = json.loads((HERE / "expected.json").read_text())
CASES = {c["case"]: c for c in FIX["cases"]}


def run(policy, case_id):
    return X.Run(policy, CASES[case_id]).run()


class Frozen(unittest.TestCase):
    def test_inputs_match_the_hashes_frozen_before_implementation(self):
        frozen = dict(line.split()[::-1] for line in (HERE / "frozen-hashes.txt").read_text().splitlines())
        for name in ("fixtures.json", "expected.json"):
            self.assertEqual(hashlib.sha256((HERE / name).read_bytes()).hexdigest(), frozen[name], name)

    def test_fixtures_are_labelled_synthetic_and_cover_the_matrix(self):
        self.assertTrue(FIX["synthetic"])
        self.assertEqual(len(CASES), 11)
        self.assertEqual(set(CASES), set(EXP["cases"]))


class Corrected(unittest.TestCase):
    def test_every_case_meets_the_frozen_expectation(self):
        for cid in CASES:
            with self.subTest(case=cid):
                self.assertEqual(X.matches(run("corrected", cid), EXP["cases"][cid]["corrected"]), [])

    def test_current_completion_is_admitted_without_deferral(self):
        got = run("corrected", "current")
        self.assertEqual(got["final"]["hotel"], {"status": "current", "active": "c1"})

    def test_delayed_old_result_cannot_overwrite_the_newer_one(self):
        got = run("corrected", "out-of-order")
        self.assertEqual(got["final"]["hotel"]["active"], "c2")
        self.assertIn(["c1", "superseded"], got["receipts"])

    def test_duplicate_is_idempotent_and_collision_is_rejected(self):
        dup = run("corrected", "duplicate")
        self.assertEqual([o for _, o in dup["receipts"]], ["admitted", "duplicate"])
        col = run("corrected", "id-collision")
        self.assertEqual([o for _, o in col["receipts"]], ["admitted", "rejected-mismatch"])
        self.assertEqual(col["active_payload"]["hotel"], "Hotel Alfama, 3 nights")

    def test_a_correction_on_one_key_does_not_block_another(self):
        got = run("corrected", "independent-keys")
        self.assertEqual(got["final"]["flight"], {"status": "current", "active": "cf1"})
        self.assertEqual(got["final"]["hotel"]["status"], "pending")

    def test_conflict_is_visible_and_needs_an_explicit_resolution(self):
        got = run("corrected", "competing-corrections")
        self.assertEqual(got["checkpoints"]["7"]["hotel"], {"status": "conflict", "active": None})
        self.assertEqual(got["final"]["hotel"], {"status": "current", "active": "ca"})

    def test_missing_update_is_admitted_then_demoted_and_that_is_the_documented_limit(self):
        got = run("corrected", "missing-update")
        self.assertEqual(got["checkpoints"]["4"]["hotel"]["active"], "c1")
        self.assertEqual(got["final"]["hotel"]["status"], "pending")


class Properties(unittest.TestCase):
    """Rules checked across every case's trace."""

    def test_nothing_received_is_ever_dropped_from_history(self):
        for cid, case in CASES.items():
            n = sum(e["type"] == "complete" for e in case["events"])
            for p in X.POLICIES:
                with self.subTest(case=cid, policy=p):
                    self.assertEqual(len(run(p, cid)["history"]), n)

    def test_no_active_result_after_a_recorded_cancellation(self):
        for cid in CASES:
            cancelled = set()
            for row in run("corrected", cid)["trace"]:
                if row["event"] == "decide" and row["action"] == "cancelled":
                    cancelled.add(row["key"])
                elif row["event"] == "decide":
                    cancelled.discard(row["key"])
                if row["key"] in cancelled:
                    with self.subTest(case=cid, tick=row["tick"]):
                        self.assertIsNone(row["view_after"]["active"])

    def test_no_active_result_while_the_authority_has_competing_heads(self):
        for cid in CASES:
            for row in run("corrected", cid)["trace"]:
                if row["authority"]["status"] == "conflict":
                    with self.subTest(case=cid, tick=row["tick"]):
                        self.assertEqual(row["view_after"], {"status": "conflict", "active": None})

    def test_an_active_result_always_belongs_to_the_authority_head(self):
        for cid in CASES:
            r = X.Run("corrected", CASES[cid])
            r.run()
            for key, view in r.views.items():
                if view.active:
                    head = r.auth[key].state()["heads"]
                    dec = r.store[view.active]["decision"]
                    adopted = r.auth[key].decisions[head[0]].get("adopt") == view.active
                    with self.subTest(case=cid, key=key):
                        self.assertTrue(dec in head or adopted)

    def test_runs_are_repeatable_and_results_file_is_current(self):
        a = X.evaluate(FIX, EXP)
        b = X.evaluate(FIX, EXP)
        self.assertEqual(a, b)
        on_disk = json.loads((HERE / "results.json").read_text())
        self.assertEqual(on_disk, json.loads(json.dumps(a)))


class Controls(unittest.TestCase):
    """The baselines must fail where predicted, or the harness can't see the bug."""

    def test_naive_lets_the_delayed_old_result_win(self):
        self.assertEqual(run("naive", "out-of-order")["final"]["hotel"]["active"], "c1")

    def test_naive_resurrects_a_cancelled_goal(self):
        self.assertEqual(run("naive", "cancel-before")["final"]["hotel"]["active"], "c1")

    def test_naive_lets_arrival_order_pick_a_conflict_winner(self):
        self.assertEqual(run("naive", "competing-corrections")["checkpoints"]["7"]["hotel"]["active"], "cb")

    def test_broken_guard_fails_only_the_race(self):
        failed = [c for c in CASES if X.matches(run("broken_guard", c), EXP["cases"][c]["corrected"])]
        self.assertEqual(failed, ["check-write-race"])
        self.assertEqual(run("broken_guard", "check-write-race")["final"]["hotel"]["active"], "c1")

    def test_every_policy_matches_its_frozen_prediction(self):
        for cid in CASES:
            for p in X.POLICIES:
                with self.subTest(case=cid, policy=p):
                    self.assertEqual(X.matches(run(p, cid), EXP["cases"][cid][p]), [])


if __name__ == "__main__":
    unittest.main()
