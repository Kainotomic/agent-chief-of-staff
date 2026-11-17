"""Property tests on the coordinator's own invariants (docs/verification.md). Standard library only: each property
draws many cases from a seeded generator, so a failure is reproducible and names the case that broke it.
Run from this directory: python3 -m unittest -v test_properties"""
import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import dispatch_guard as dg
import ledger_store as ls

T0 = datetime(2026, 1, 16, 14, 0, tzinfo=timezone.utc)
CASES = 300

# Text that has broken table rows before: pipes, every line boundary splitlines() knows, tabs, padding, dashes,
# backticks, non-ASCII, and the empty-cell markers.
PIECES = ["a", "word", "R-001", "ISSUE-12", "|", "||", "\n", "\r\n", "\r", "\x0b", "\x0c", "\x1c", "\x85", " ",
          " ", "\t", " ", "  ", "—", "-", "`", "\\", "\\|", "é", "日本", "😀", "~05:05Z", "x" * 120, "<b>", "#"]


def text(rng, most=12):
    return "".join(rng.choice(PIECES) for _ in range(rng.randint(0, most)))


class TempDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class RowReadBack(TempDir):
    def test_a_written_row_reads_back_identical(self):
        rng = random.Random(412)
        led = ls.Ledger(self.root)
        ids = []
        for case in range(CASES):
            fields = {f: text(rng) for f in rng.sample(["key", "owner", "next", "waits", "due"], rng.randint(1, 5))}
            row_id = rng.choice(ids) if ids and rng.random() < 0.5 else None
            if row_id is None:
                fields.setdefault("next", "a")
            try:
                written = led.write_row(row_id, **fields)
            except ValueError:  # a blank next action is refused, which is the invariant for that case
                self.assertIn(ls.clean(fields.get("next", "x")), ls.NONE, f"case {case}: {fields!r}")
                continue
            ids.append(written["id"])
            read = {r["id"]: {k: r[k] for k in ls.FIELDS} for r in led.rows()}
            self.assertEqual(read[written["id"]], written, f"case {case}: wrote {fields!r}")
            self.assertTrue(all(r["_cols"] == len(ls.COLUMNS) for r in led.rows()), f"case {case}: {fields!r}")


class ApproximateTimes(TempDir):
    """Proof and due cells carry the real minute. An approximate or placeholder time is refused in every spelling."""

    MARKS = ["~", "~ ", "≈", "∼ ", "about ", "About ", "approx ", "approx. ", "approximately ", "around ", "circa ",
             "ca. ", "roughly "]
    PLACEHOLDERS = ["xx:xx", "XX:XX", "xx:xxZ", "hh:mm", "HH:MMZ", "??:??", "--:--Z", "05:xxZ", "xx:05Z", "5:x5Z"]
    ZONES = ["Z", " UTC", "", " PT"]

    def stamps(self, rng):
        for _ in range(CASES):
            hour = rng.choice([f"{rng.randint(0, 23):02d}", str(rng.randint(0, 9))])
            yield f"{rng.choice(self.MARKS)}{hour}:{rng.randint(0, 59):02d}{rng.choice(self.ZONES)}"
        for p in self.PLACEHOLDERS:
            yield p

    def test_owner_proof_refuses_an_approximate_or_placeholder_time(self):
        rng = random.Random(4121)
        for stamp in self.stamps(rng):
            ref = f'"{rng.choice(["go ahead", "yes, ship it", "merge it"])}" 2026-01-16 {stamp}'
            self.assertIsNotNone(ls.proof_problem("owner", ref, "the owner approved the plan"), ref)

    def test_owner_proof_keeps_an_exact_time(self):
        rng = random.Random(4122)
        for _ in range(CASES):
            hour = rng.choice([f"{rng.randint(0, 23):02d}", str(rng.randint(0, 9))])
            ref = f'"go ahead" 2026-01-16 {hour}:{rng.randint(0, 59):02d}{rng.choice(self.ZONES)}'
            self.assertIsNone(ls.proof_problem("owner", ref, "the owner approved the plan"), ref)

    def test_due_refuses_an_approximate_or_placeholder_time(self):
        rng = random.Random(4123)
        led = ls.Ledger(self.root)
        for stamp in self.stamps(rng):
            row = led.write_row(None, next="look again", due=f"01-17 {stamp}")
            errors, _ = led.check()
            self.assertTrue(any(row["id"] in e and "due" in e for e in errors), f"due {stamp!r}: {errors}")
            led.write_row(row["id"], due="—")


class ProseIsNotProof(unittest.TestCase):
    """A close whose ref is only prose is refused for every kind. void is the exception by design: its ref is the
    reason, so prose naming a test or accident is what it takes (the vocabulary leaves those words out)."""

    WORDS = ["the", "build", "looks", "healthy", "success", "passed", "PASS", "OK", "green", "merged", "deployed",
             "read", "back", "readback", "status", "live", "ready", "exit", "commit", "sha", "run", "id", "review",
             "comment", "owner", "approved", "said", "yes", "ci", "tests", "Ran", "all", "checks", "on", "main",
             "head", "service", "answers", "now", "after", "restart", "setting", "value", "is", "set", "message",
             "sent", "folded", "into", "row", "R", "accede", "acceded", "defaced", "effaced", "deadbeef", "facade",
             "decaf", "cabbed", "beaded", "faded", "added", "fed", "bed", "cafe"]

    def test_prose_only_proof_is_refused_for_every_kind(self):
        rng = random.Random(4124)
        for kind in ls.PROOF_KINDS:
            if kind == "void":
                continue
            for _ in range(CASES):
                ref = " ".join(rng.choice(self.WORDS) for _ in range(rng.randint(1, 8)))
                problem = ls.proof_problem(kind, ref, "what the ref proves")
                self.assertIsNotNone(problem, f"{kind}: prose ref {ref!r} was accepted")

    def test_void_needs_a_reason_word(self):
        rng = random.Random(4125)
        words = [w for w in self.WORDS if not ls.VOID_REASON.search(w)]
        for _ in range(CASES):
            ref = " ".join(rng.choice(words) for _ in range(rng.randint(1, 8)))
            self.assertIsNotNone(ls.proof_problem("void", ref, "closed"), ref)


class FoundByTheProperties(TempDir):
    """The gaps the properties above found in this repo, as named cases."""

    def test_a_word_made_of_hex_letters_is_not_a_sha(self):
        for word in ("defaced", "acceded", "deadbeef", "effaced"):
            self.assertIsNotNone(ls.proof_problem("merged", word, "merged the PR"), word)
            self.assertIsNotNone(ls.proof_problem("ci", f"{word} success", "checks on the head"), word)

    def test_a_real_sha_still_closes(self):
        for sha in ("89f09d6", "89f09d6c0ffee1234567890abcdef1234567890", "a" * 40, "abcdefabcdef"):
            self.assertIsNone(ls.proof_problem("merged", sha, "merged the PR"), sha)
            self.assertIsNone(ls.proof_problem("ci", f"{sha} success", "checks on the head"), sha)

    def test_config_needs_the_setting_not_the_words_read_back(self):
        for ref in ("readback", "read back", "read back the value"):
            self.assertIsNotNone(ls.proof_problem("config", ref, "flag off"), ref)
        self.assertIsNone(ls.proof_problem("config", "autoDeploy=false read back", "flag off"))

    def test_an_owner_proof_with_a_rough_time_does_not_close(self):
        led = ls.Ledger(self.root)
        row = led.write_row(None, owner="owner", next="Pick a price", waits="owner: decision")
        with self.assertRaises(ls.ProofRefused):
            led.close_row(row["id"], "owner", '"A" 2026-01-16 ~14:02Z', "price A chosen", now=T0)
        led.close_row(row["id"], "owner", '"A" 2026-01-16 14:02Z', "price A chosen", now=T0)
        self.assertEqual(led.rows(), [])


class OneLiveClaimPerRow(TempDir):
    """Two live claims on one row are refused, with or without a tracker key."""

    def setUp(self):
        super().setUp()
        self.claims = dg.Claims(self.root / "claims.json")
        self.clear = dg.Sources(open_prs_naming=lambda key: [], assignee=lambda key: None, live_workers=lambda: [])

    def test_a_second_session_is_refused_on_a_claimed_row(self):
        rng = random.Random(4126)
        for case in range(CASES):
            row = f"R-{case + 1:03d}"
            key = rng.choice([None, "", f"ISSUE-{case}"])
            first, second = f"coordinator-{rng.getrandbits(24):06x}", f"coordinator-{rng.getrandbits(24):06x}"
            if first == second:
                continue
            self.claims.claim([row], first, "worker-aaaaaa", T0)
            verdict = dg.guard(key, row, second, self.clear, self.claims, now=T0)
            self.assertFalse(verdict.allowed, f"case {case}: key {key!r}, row {row} claimed by {first}")
            with self.assertRaises(dg.ClaimHeld, msg=f"case {case}: key {key!r}"):
                self.claims.claim([row], second, "worker-bbbbbb", T0)
            self.assertTrue(dg.guard(key, row, first, self.clear, self.claims, now=T0).allowed, f"case {case}")

    def test_a_live_worker_on_the_row_refuses_without_a_key(self):
        rng = random.Random(4127)
        for case in range(CASES):
            row = f"R-{case + 1:03d}"
            key = rng.choice([None, ""])
            worker = {"id": f"worker-{rng.getrandbits(24):06x}", "row": row, "key": None, "host": "host-a"}
            busy = dg.Sources(open_prs_naming=lambda k: [], assignee=lambda k: None, live_workers=lambda: [worker])
            verdict = dg.guard(key, row, "coordinator-a1", busy, self.claims, now=T0)
            self.assertFalse(verdict.allowed, f"case {case}: {worker}")


if __name__ == "__main__":
    unittest.main()
