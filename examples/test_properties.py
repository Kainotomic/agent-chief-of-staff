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
PIECES = ["a", "word", "R-001", "ISSUE-12", "|", "||", "\n", "\r\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ",
          " ", "\t", " ", "  ", "—", "-", "`", "\\", "\\|", "é", "日本", "😀", "~05:05Z", "x" * 8, "<b>", "#"]


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
        expected_rows = {}
        for case in range(CASES):
            fields = {f: text(rng, most=10) for f in rng.sample(["key", "owner", "next", "waits", "due"], rng.randint(1, 5))}
            row_id = rng.choice(list(expected_rows)) if expected_rows and rng.random() < 0.5 else None
            if row_id is None:
                fields.setdefault("next", "a")
                expected = {"id": f"R-{len(expected_rows) + 1:03d}", "key": "—", "owner": "coordinator",
                            "next": "", "waits": "—", "due": "—"}
            else:
                expected = expected_rows[row_id].copy()
            expected.update({field: " ".join(value.splitlines()).replace("|", "/").strip()
                             for field, value in fields.items()})
            with self.subTest(case=case, row_id=row_id, fields=fields):
                if expected["next"] in ("", "—", "-"):
                    with self.assertRaisesRegex(ValueError, "next action is required"):
                        led.write_row(row_id, **fields)
                else:
                    self.assertEqual(led.write_row(row_id, **fields), expected)
                    expected_rows[expected["id"]] = expected
                rows = ls.Ledger(self.root).rows()
                self.assertEqual({row["id"]: {k: row[k] for k in expected} for row in rows}, expected_rows)
                self.assertTrue(all(row["_cols"] == 6 for row in rows))

    def test_spilled_row_keeps_the_wait_and_preserves_full_text_in_note(self):
        led = ls.Ledger(self.root)
        long_next = "Read | the log\n" + "output " * 90 + "end"
        waits = "owner: decision; then review results"
        led.write_row(None, next=long_next, waits=waits)

        read, = ls.Ledger(self.root).rows()
        self.assertEqual(read["waits"], waits)
        self.assertEqual(ls.queue_of(read), "DECISION")
        pointer = " (detail: ledger/notes/R-001.md)"
        self.assertTrue(read["next"].endswith(pointer))
        expected_next = "Read / the log " + "output " * 90 + "end"
        self.assertTrue(expected_next.startswith(read["next"].removesuffix(pointer)))
        self.assertLessEqual(ls.row_chars(read), 500)
        self.assertIn(f"next action: {expected_next}\nwaits on: {waits}\n",
                      (self.root / "ledger" / "notes" / "R-001.md").read_text())


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

    def test_owner_proof_refuses_an_approximate_date_or_impossible_timestamp(self):
        rng = random.Random(4128)
        stamps = ["circa 2026-01-16 14:02Z", "2026-01-16 29:99Z", "2026-02-29 14:02Z"]
        for _ in range(CASES):
            hour, minute = rng.randrange(24), rng.randrange(60)
            zone = rng.choice(self.ZONES)
            stamps.extend((
                f"{rng.choice(self.MARKS)}2026-01-16 {hour:02d}:{minute:02d}{zone}",
                f"2026-01-16 {rng.randrange(24, 100)}:{minute:02d}{zone}",
                f"2026-01-16 {hour:02d}:{rng.randrange(60, 100)}{zone}",
                f"2026-02-{rng.randrange(29, 32)} {hour:02d}:{minute:02d}{zone}",
            ))
        for stamp in stamps:
            with self.subTest(stamp=stamp):
                self.assertIsNotNone(ls.proof_problem("owner", f'"Ship it" {stamp}', "decision recorded"))

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

    def test_a_trusted_merge_lookup_can_verify_a_short_letter_only_sha(self):
        lookups = []

        def lookup(repo, number):
            lookups.append((repo, number))
            return "fcaabad1234567890abcdef1234567890abcdef1"

        policy = ls.compose_close_policies(lambda row, proof: None, ls.pr_merge_policy(lookup))
        led = ls.Ledger(self.root, can_close=policy)
        row = led.write_row(None, next="Merge acme/widgets#16")
        with self.assertRaises(ls.ProofRefused):
            ls.Ledger(self.root, can_close=lambda row, proof: None).close_row(
                row["id"], "merged", "fcaabad", "merged the PR", now=T0)
        with self.assertRaises(ls.CloseRefused):
            led.close_row(row["id"], "merged", "defaced", "merged the PR", now=T0)
        led.close_row(row["id"], "merged", "fcaabad", "merged the PR", now=T0)
        self.assertEqual(lookups, [("acme/widgets", 16)] * 2)
        self.assertEqual(ls.Ledger(self.root).check(), ([], []))

        no_pr = led.write_row(None, next="Merge the fix")
        with self.assertRaises(ls.CloseRefused):
            led.close_row(no_pr["id"], "merged", "fcaabad", "merged locally", now=T0)
        self.assertEqual(len(lookups), 2)

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

    def test_a_new_owner_quote_with_a_leading_apostrophe_passes_archive_check(self):
        led = ls.Ledger(self.root)
        row = led.write_row(None, next="Record the owner's decision")
        led.close_row(row["id"], "owner", '"’twas time" 2026-01-16 14:02Z', "decision recorded", now=T0)
        self.assertEqual(led.check(), ([], []))

    def test_the_owner_s_own_words_may_name_a_rough_time(self):
        words = ("Schedule the deploy around 5:00 UTC", "ship it ~05:00Z", "after xx:xx is fine",
                 "don't deploy around 5:00 UTC", "don’t deploy around 5:00 UTC", "it's fine, ship ~5:00",
                 "Use the vendors’ prices around 5:00 UTC", "Use the vendors' prices around 5:00 UTC")
        quotes = (('"', '"'), ("“", "”"), ("‘", "’"), ("'", "'"))
        for said in words:
            for left, right in quotes:
                quoted = f"{left}{said}{right}"
                self.assertIsNone(ls.proof_problem("owner", f"{quoted} 2026-01-16 14:02Z", "decided"), quoted)
                self.assertIsNotNone(ls.proof_problem("owner", f"{quoted} 2026-01-16", "decided"), quoted)
                self.assertIsNotNone(ls.proof_problem("owner", f"{quoted} 2026-01-16 ~14:02Z", "decided"), quoted)

    def test_owner_proof_needs_a_nonempty_paired_quote(self):
        for quote in ('" "', "‘ ’", "' '", '"ship it’', '‘ship it"', "'ship it”"):
            with self.subTest(quote=quote):
                self.assertIsNotNone(ls.proof_problem("owner", f"{quote} 2026-01-16 14:02Z", "decision recorded"))
        for stamp in ("14:02Z", "2024-02-29 5:02 UTC"):
            with self.subTest(stamp=stamp):
                self.assertIsNone(ls.proof_problem("owner", f'"Ship it" {stamp}', "decision recorded"))


class ArchiveCompatibility(TempDir):
    # Every ref was closed and checked by main (59074d02). Each pair lists refs
    # accepted for both paths, then refs accepted only in the archive.
    MAIN_PROOFS = {
        "tests": (("Ran 88", "88 tests", "88 passed", "88 passing", "0 failed", "0 failures", "0 errors",
                   "1 skipped; OK", "64/64", "88 OK", "OK (integration suite)", "run 419828"), ()),
        "ci": (("run 419828 completed/success", "89f09d6 success", "abcdefabcdef success"),
               ("fcaabad success", "abcdefabcde success")),
        "merged": (("89f09d6", "abcdefabcdef", "a" * 40), ("fcaabad", "abcdefabcde")),
        "deployed": (("deploy dep-4417, readyz 200", "build-4417 healthy"), ()),
        "config": (("autoDeploy=false", "autoDeploy -> false", "autoDeploy → false"),
                   ("read back autoDeploy", "read back ok", "READ-BACK autoDeploy", "readback")),
        "message": (("issuecomment-3456789", "1234"), ()),
        "owner": (('"ship it" 2026-01-16 14:02Z', "'go' 14:02 UTC"),
                  ('"ship it" 2026-01-16 14:02 EST', '"ship it" 2026-01-16 14:02:30Z', '"go" at 14:02Z',
                   'Andrew: "ship it" 14:02Z', '"ship it" (14:02Z)', '"ship it" circa 2026-01-16 14:02Z',
                   '"ship it" 2026-01-16 29:99Z', '"ship it" 2026-02-30 14:02Z', '"wait until 5:00 UTC"')),
        "folded": (("R-001",), ()),
        "void": (("unit test", "queued tests", "testing queue", "fixture row", "accidental duplicate",
                  "mistaken duplicate", "opened in error", "opened by error", "typo in title", "stray row",
                  "created by setup"), ()),
    }

    def assert_archive_compatibility(self, kind):
        new_refs, archive_only = self.MAIN_PROOFS[kind]
        refs = new_refs + archive_only
        archived = ls.Ledger(self.root / "previous")
        archive_path = archived.root / "ledger" / "closed-2026-01.md"
        archive_path.parent.mkdir(parents=True)
        archive_path.write_text(
            "| id | key | closed | proof | last next action |\n|---|---|---|---|---|\n"
            + "".join(f"| R-{number:03d} | — | 2026-01-16 14:00Z | {kind}: {ref} - x | Record evidence |\n"
                      for number, ref in enumerate(refs, 2))
        )
        with self.subTest(path="archive"):
            self.assertEqual(len(archived.closed_rows()), len(refs))
            self.assertEqual(archived.check(), ([], []))

        led = ls.Ledger(self.root / "new")
        if kind == "folded":
            led.write_row(None, next="Carry follow-ups for R-002")
        for ref in new_refs:
            with self.subTest(path="new close", ref=ref):
                row = led.write_row(None, next="Record evidence")
                led.close_row(row["id"], kind, ref, "x", now=T0)
        if archive_only:
            row = led.write_row(None, next="Record legacy evidence")
            for ref in archive_only:
                with self.subTest(path="new close", ref=ref), self.assertRaises(ls.ProofRefused):
                    led.close_row(row["id"], kind, ref, "x", now=T0)
        self.assertEqual(len(led.closed_rows()), len(new_refs))
        self.assertEqual(led.check(), ([], []))

    def test_fixture_table_covers_every_proof_kind(self):
        self.assertEqual(set(self.MAIN_PROOFS), set(ls.PROOF_KINDS))

    def test_tests_compatibility(self):
        self.assert_archive_compatibility("tests")

    def test_ci_compatibility(self):
        self.assert_archive_compatibility("ci")

    def test_merged_compatibility(self):
        self.assert_archive_compatibility("merged")

    def test_deployed_compatibility(self):
        self.assert_archive_compatibility("deployed")

    def test_config_compatibility(self):
        self.assert_archive_compatibility("config")

    def test_message_compatibility(self):
        self.assert_archive_compatibility("message")

    def test_owner_compatibility(self):
        self.assert_archive_compatibility("owner")

    def test_folded_compatibility(self):
        self.assert_archive_compatibility("folded")

    def test_void_compatibility(self):
        self.assert_archive_compatibility("void")


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
