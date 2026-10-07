"""Stale-completion admission: a deterministic local model.

An agent job is started against a decision (the user's goal at that moment). While it runs,
the user may correct or cancel the goal. When the job's result arrives, something has to
decide whether that result may become the active value. This file replays authored
synthetic schedules (fixtures.json) under three policies:

  naive         newest arrival overwrites the active value
  broken_guard  checks the decision when the result arrives, then writes later without rechecking
  corrected     checks and writes in one non-yielding step, against the authority's current decision

The "authority" is a single in-process record of decisions per (scope, key). Decisions point at
the decision(s) they replace; order comes from those links, never from timestamps. Ticks are
integer ordering devices, not latency. This is a local model: it does not implement distributed
atomicity. A real multi-writer system has to enforce the same condition at its storage boundary.

Standard library only. Run:
  python3 experiment.py --fixtures fixtures.json --out results.json [--trace trace.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field

POLICIES = ("naive", "broken_guard", "corrected")


def digest(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- authority (per key)

@dataclass
class Authority:
    decisions: dict = field(default_factory=dict)  # id -> {"parents": [...], "kind": ..., "adopt": ...}

    def add(self, dec: str, parents: list, kind: str, adopt: str | None):
        self.decisions[dec] = {"parents": list(parents), "kind": kind, "adopt": adopt}

    def heads(self) -> list:
        replaced = {p for d in self.decisions.values() for p in d["parents"]}
        return sorted(d for d in self.decisions if d not in replaced)

    def ancestors(self, dec: str) -> set:
        seen, stack = set(), list(self.decisions.get(dec, {}).get("parents", []))
        while stack:
            p = stack.pop()
            if p not in seen:
                seen.add(p)
                stack.extend(self.decisions.get(p, {}).get("parents", []))
        return seen

    def state(self) -> dict:
        h = self.heads()
        if not h:
            return {"status": "empty", "heads": []}
        if len(h) > 1:
            return {"status": "conflict", "heads": h}
        kind = self.decisions[h[0]]["kind"]
        return {"status": "cancelled" if kind == "cancel" else "open", "heads": h, "kind": kind}

    def copy(self) -> "Authority":
        return Authority({k: {**v, "parents": list(v["parents"])} for k, v in self.decisions.items()})


# ---------------------------------------------------------------- admission decision

def classify(auth: Authority, decision: str) -> tuple[str, str]:
    """What a result started under `decision` is, given what the authority knows now."""
    st = auth.state()
    if decision not in auth.decisions:
        return "rejected-unknown-decision", "the authority has no record of this decision"
    if st["status"] == "conflict":
        if decision in st["heads"]:
            return "held-conflict", f"{len(st['heads'])} decisions replace the same parent; none is current until resolved"
        return "superseded", "replaced by later decisions"
    head = st["heads"][0]
    if decision == head and st["status"] == "open":
        return "admitted", "result is for the current decision"
    if decision in auth.ancestors(head):
        if st["status"] == "cancelled":
            return "cancelled", f"goal was cancelled by {head}"
        return "superseded", f"replaced by {head}"
    return "rejected-unknown-decision", "decision is not on the current line"


# ---------------------------------------------------------------- one policy run

@dataclass
class KeyView:
    status: str = "pending"  # pending | current | cancelled | conflict
    active: str | None = None
    payload: str | None = None

    def snap(self) -> dict:
        return {"status": self.status, "active": self.active}


class Run:
    def __init__(self, policy: str, case: dict):
        self.policy = policy
        self.case = case
        self.auth: dict[str, Authority] = {}
        self.views: dict[str, KeyView] = {}
        self.jobs: dict[str, dict] = {}
        self.store: dict[str, dict] = {}  # completion id -> first receipt (history, never deleted)
        self.receipts: list = []          # arrival-order outcomes
        self.history: list = []           # every result ever received, with its outcome
        self.pending_checks: dict = {}    # broken_guard: (completion,tick) -> verdict computed at check time
        self.trace: list = []
        self.checkpoints: dict = {}

    def a(self, key):
        return self.auth.setdefault(key, Authority())

    def v(self, key):
        return self.views.setdefault(key, KeyView())

    def log(self, tick, key, etype, action, reason, before, extra=None):
        st = self.a(key).state()
        row = {
            "case": self.case["case"], "policy": self.policy, "tick": tick, "key": key, "event": etype,
            "authority": {"status": st["status"], "heads": st["heads"]},
            "action": action, "reason": reason,
            "view_before": before, "view_after": self.v(key).snap(),
            "history_size": len(self.history),
        }
        if extra:
            row.update(extra)
        self.trace.append(row)

    # -- authority events: update the active view from what the authority now says
    def on_decide(self, e):
        key, before = e["key"], self.v(e["key"]).snap()
        self.a(key).add(e["decision"], e["parents"], e["kind"], e.get("adopt"))
        view = self.v(key)
        if self.policy == "naive":
            self.log(e["tick"], key, "decide", "ignored", "naive overwrite does not read decisions", before, {"decision": e["decision"]})
            return
        st = self.a(key).state()
        if st["status"] == "conflict":
            view.status, view.active, view.payload = "conflict", None, None
            action, reason = "conflict", f"{', '.join(st['heads'])} both replace the same parent"
        elif st["status"] == "cancelled":
            view.status, view.active, view.payload = "cancelled", None, None
            action, reason = "cancelled", "goal cancelled; earlier admissions stay in history"
        else:
            adopt = e.get("adopt")
            if adopt and adopt in self.store:
                view.status, view.active, view.payload = "current", adopt, self.store[adopt]["payload"]
                action, reason = "resolved", f"explicit resolution {e['decision']} adopts {adopt}"
            elif view.active and self.store[view.active]["decision"] == st["heads"][0]:
                action, reason = "kept", "active result already matches the decision"
            else:
                view.status, view.active, view.payload = "pending", None, None
                action, reason = "awaiting", f"waiting for a result for {st['heads'][0]}"
        self.log(e["tick"], key, "decide", action, reason, before, {"decision": e["decision"]})

    def on_start(self, e):
        self.jobs[e["job"]] = {"key": e["key"], "decision": e["decision"], "content": e["content"]}
        self.log(e["tick"], e["key"], "start", "started", f"job {e['job']} bound to {e['decision']}", self.v(e["key"]).snap(), {"job": e["job"]})

    def on_external(self, e):
        self.log(e["tick"], e["key"], "external", "unseen", "change exists outside the modeled authority", self.v(e["key"]).snap())

    # -- the check (for broken_guard this happens earlier than the write)
    def verdict(self, e, auth: Authority) -> tuple[str, str]:
        comp, payload = e["completion"], e["payload"]
        if comp in self.store:
            if self.store[comp]["digest"] == digest(payload):
                return "duplicate", "same completion ID and payload already received"
            return "rejected-mismatch", "completion ID reused with different content"
        return classify(auth, self.jobs[e["job"]]["decision"])

    def on_check(self, e):
        self.pending_checks[e["completion"], e["tick"]] = self.verdict(e, self.a(e["key"]).copy())
        self.log(e["check_tick"], e["key"], "check", "checked", "guard read the decision (write happens later)",
                 self.v(e["key"]).snap(), {"completion": e["completion"], "verdict": self.pending_checks[e["completion"], e["tick"]][0]})

    def on_complete(self, e):
        key, comp, payload = e["key"], e["completion"], e["payload"]
        before = self.v(key).snap()
        base = self.jobs[e["job"]]["decision"]
        view = self.v(key)
        if self.policy == "naive":
            outcome, reason = "admitted", "newest arrival wins"
        elif self.policy == "broken_guard":
            outcome, reason = self.pending_checks.pop((comp, e["tick"]), None) or self.verdict(e, self.a(key))
            reason += " (verdict from the earlier check; not rechecked at write)"
        else:
            outcome, reason = self.verdict(e, self.a(key))
        if comp not in self.store:
            self.store[comp] = {"payload": payload, "digest": digest(payload), "decision": base, "outcome": outcome}
        self.history.append({"completion": comp, "decision": base, "payload": payload, "outcome": outcome, "tick": e["tick"]})
        self.receipts.append([comp, outcome])
        if outcome == "admitted":
            view.status, view.active, view.payload = "current", comp, payload
        self.log(e["tick"], key, "complete", outcome, reason, before, {"completion": comp, "result_decision": base})

    def run(self) -> dict:
        events = []
        for i, e in enumerate(self.case["events"]):
            if e["type"] == "complete" and self.policy == "broken_guard" and "check_tick" in e:
                events.append((e["check_tick"], i, "check", e))
            events.append((e["tick"], i, e["type"], e))
        events.sort(key=lambda x: (x[0], x[1]))
        handlers = {"decide": self.on_decide, "start": self.on_start, "complete": self.on_complete, "external": self.on_external, "check": self.on_check}
        last_tick = None
        for tick, _, etype, e in events:
            if last_tick is not None and tick != last_tick:
                self.checkpoints[str(last_tick)] = {k: v.snap() for k, v in sorted(self.views.items())}
            handlers[etype](e)
            last_tick = tick
        if last_tick is not None:
            self.checkpoints[str(last_tick)] = {k: v.snap() for k, v in sorted(self.views.items())}
        return {
            "final": {k: v.snap() for k, v in sorted(self.views.items())},
            "active_payload": {k: v.payload for k, v in sorted(self.views.items())},
            "receipts": self.receipts,
            "history": self.history,
            "checkpoints": self.checkpoints,
            "trace": self.trace,
        }


# ---------------------------------------------------------------- compare to frozen expectations

def matches(got: dict, exp: dict, view_only: bool = False) -> list:
    """Return the list of mismatches between a run and an expectation block (empty = match).
    view_only skips receipts: it asks only whether the active value a user would see is right."""
    out = []
    for key, want in exp["final"].items():
        if got["final"].get(key) != want:
            out.append(f"final[{key}] = {got['final'].get(key)} expected {want}")
    if not view_only and got["receipts"] != exp["receipts"]:
        out.append(f"receipts = {got['receipts']} expected {exp['receipts']}")
    for tick, views in exp.get("checkpoints", {}).items():
        for key, want in views.items():
            have = got["checkpoints"].get(tick, {}).get(key)
            if have != want:
                out.append(f"tick {tick} [{key}] = {have} expected {want}")
    for key, want in exp.get("active_payload", {}).items():
        if got["active_payload"].get(key) != want:
            out.append(f"active_payload[{key}] = {got['active_payload'].get(key)!r} expected {want!r}")
    return out


def evaluate(fixtures: dict, expected: dict) -> dict:
    cases = []
    for case in fixtures["cases"]:
        exp = expected["cases"][case["case"]]
        row = {"case": case["case"], "title": case["title"], "note": case["note"], "policies": {}}
        for p in POLICIES:
            got = Run(p, case).run()
            row["policies"][p] = {
                **{k: got[k] for k in ("final", "active_payload", "receipts", "history", "checkpoints")},
                "matches_prediction": not matches(got, exp[p]),
                "prediction_mismatches": matches(got, exp[p]),
                # Desired behavior is the corrected expectation.
                "meets_desired": not matches(got, exp["corrected"]),
                "desired_mismatches": matches(got, exp["corrected"]),
                # Added after the first run: user-visible view only (final, checkpoints, payload), no receipts.
                "view_meets_desired": not matches(got, exp["corrected"], view_only=True),
            }
        cases.append(row)
    n = len(cases)
    summary = {
        p: {
            "meets_desired": sum(c["policies"][p]["meets_desired"] for c in cases),
            "matches_prediction": sum(c["policies"][p]["matches_prediction"] for c in cases),
            "view_meets_desired": sum(c["policies"][p]["view_meets_desired"] for c in cases),
            "view_failed": [c["case"] for c in cases if not c["policies"][p]["view_meets_desired"]],
            "cases": n,
            "failed_desired": [c["case"] for c in cases if not c["policies"][p]["meets_desired"]],
        }
        for p in POLICIES
    }
    return {"version": 1, "synthetic": True, "cases_total": n, "summary": summary, "cases": cases}


def traces(fixtures: dict) -> list:
    return [row for case in fixtures["cases"] for p in POLICIES for row in Run(p, case).run()["trace"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="fixtures.json")
    ap.add_argument("--expected", default="expected.json")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--trace", default="trace.json")
    args = ap.parse_args()
    fixtures = json.load(open(args.fixtures))
    expected = json.load(open(args.expected))
    results = evaluate(fixtures, expected)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(args.trace, "w") as f:
        json.dump(traces(fixtures), f, indent=1, sort_keys=True)
        f.write("\n")
    for p, s in results["summary"].items():
        print(f"{p:13s} view right {s['view_meets_desired']}/{s['cases']}  view+receipts right {s['meets_desired']}/{s['cases']}  matches prediction {s['matches_prediction']}/{s['cases']}")
        print(f"{'':13s} wrong view: {', '.join(s['view_failed']) or '-'}")


if __name__ == "__main__":
    main()
