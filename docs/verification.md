# Verification

The coordinator can hand work to workers only as far as it can check the result. Verification is what lets it delegate: a worker that proves its change end to end can be trusted with more, and a "done" without proof is just another open row.

Background: "How the Claude Code team thinks about verification" (16 Nov 2026). The rules below are how we applied it to a coordinator and its workers. What counts as proof when a row closes is in [ledger.md](ledger.md#closing-with-proof); this page is about producing that proof.

## Cheap checks first

Tests, build and lint pass before a PR is opened or a "done" is reported. They are the floor, not the proof.

## Then run it end to end

Drive the real thing through the flow you changed: the app in a browser or simulator, the CLI with real arguments, or a real authenticated call to the service.

- **Unit tests alone are not proof.** If you could not run the change end to end, say so under Unverified in the report.
- **Each repo keeps a `verify` skill** (or an equivalent short runbook the workers load). It says how to start the app locally on throwaway data, sign in as a test user, drive a flow headless with a step trace and a screenshot, what pass and fail look like, and how to clean up.
- **The skill is proven by one real run**, quoted in the PR that adds it. An untested runbook is a guess.
- **When the main branch cannot run** (a blocked dependency, say), prove the change on a local merge of main plus the fix that is never pushed, and say so in the PR.

## Three rounds, then a human

After 3 failed fix rounds on the same failure, stop. Hand it to a person with what each round tried and what it showed. A fourth round from the same angle rarely finds what the first three missed, and it hides that the problem is harder than it looked.

## Never make a test green by not running it

- Never skip, sleep or retry a failing or flaky test to get green. Fix it, or delete it with the reason recorded in the PR.
- "Pre-existing failure" is a finding to report, not a pass.
- Retries of a network call inside a running job are fine. Retries of a test are not.

## Property tests on the coordinator's own invariants

The coordinator's scripts guard everything else, so test them hardest. Write properties, not only examples:

- A fresh ledger read preserves supplied cells after normalization and preserves cells omitted from updates. Spilled text remains in the row's note.
- Approximate or placeholder times are refused, including a qualifier before the date or the clock. Owner proofs also reject impossible dates and clock times.
- a close whose proof is only prose is refused for every proof kind (`void` takes a reason, and only one naming a test or an accident);
- two live claims on one row are refused, including on a row with no tracker key ([examples/dispatch_guard.py](../examples/dispatch_guard.py) checks the row's claim and live workers whether or not there is a key).

In their first hour, properties like these found two real bugs and one dangerous test (see [lessons.md](lessons.md#testing-and-verification)). [examples/test_properties.py](../examples/test_properties.py) runs all four on this repo's examples with a seeded generator, standard library only; it found three gaps here too. **Tests stub every external call.** A test that can reach a real database, tracker or host will, one day, through a stale fixture path.

## Differential checks before a cutover

Before replacing a service, run the same inputs through the old and the new one and compare. **Set the pass bar before you start**, so the result cannot argue you into it.

| service | inputs | pass bar |
|---|---|---|
| Memory service | 20 real recall queries | Same top result on all 20; at least 8 of the top 10 overlap; row counts equal |
| Model gateway | The same real calls | Same status and same model id on every call |

- **Keep the old service running until a real caller succeeds after the flip.** The comparison proves the new service; a caller proves the wiring.
- **A dump and restore is not a copy.** If it rebuilds an index and the results change, copy the data volume byte for byte instead.
- **Embed where you serve.** Vectors made on one runtime (a GPU) and queries embedded on another (a CPU) drift a little, enough to reorder close results. Re-embed everything on the runtime that will serve queries.

## Moving files

Write a per-file checksum manifest at the source, verify every file at the target against it, and only then delete the source. A matching file count is not a match.

## Latency is part of done

A service that answers correctly but slower than its callers' timeout (a hook with a 10-second limit, say) is not done. Measure the call the way the caller makes it, and quote the time.

## A worker's "verified" is not proof

Before closing a row, the coordinator reads one artifact itself: the CI conclusion on the head SHA, the read-back, the screenshot or step trace, a fresh call to the live flow. A sub-agent's summary that says "verified" is a claim; `close_row` refuses it (see [ledger.md](ledger.md#closing-with-proof)).
