# Changelog

All notable changes to DatasetDoctor are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [0.2.4] - 2026-11-06

### Fixed

A scale & performance and error-message-quality QA round (realistic
large files, hostile inputs, and a 300-trial property test of the
similarity pass against a brute-force oracle) found two defects.

- **`check` failed valid files that start with an unrecognized
  record.** A single generic line (e.g. a metadata record such as
  `{"foo": "bar"}` at the top of the file) locked the file's format
  to "generic", so every well-formed chat or prompt/completion
  record after it was reported as a mixed-format error and the
  check failed with exit code 1. A generic record has no format of
  its own: it now keeps only its existing warning ("unrecognized
  record shape — only JSON validity was checked") and neither locks
  the file format nor counts as a format mismatch, in either
  position. A file of only generic records still reports format
  "generic"; a genuinely mixed chat + prompt/completion file still
  fails with the mixed-format error.
- **`check` / `leakage` with `--similarity` were quadratic on
  duplicate-heavy and heavily templated files.** Each example's
  candidate set was built by unioning every earlier example sharing
  a prefix shingle, so a 20,000-line file of identical examples took
  ~81 s to check (~5 s at 5,000 lines), a 20,000-line templated
  file ~88 s, and `leakage --similarity` on two such 20,000-line
  files ~246 s. Two changes in `similar_pairs`: candidates are now
  visited lazily in position order (a merge of the per-shingle
  position lists) so a scan stops at the first similar earlier
  example without materializing the whole candidate set, and an
  example that duplicates an already-indexed example of its own
  duplicate cluster (identical shingle set) is not indexed at all —
  it can never be any later example's earliest non-skipped similar
  match. After the fix the same three cases take ~10 s / ~23 s /
  ~14 s wall on this VM, down from ~81 s / ~88 s / ~246 s (the
  remaining time is dominated by the pre-existing per-line
  validation cost — profiling shows the similarity pass itself is no
  longer the bottleneck), and doubling a duplicate-heavy input now
  scales ~2x instead of ~4x.
  `leakage` now also passes the normalized-hash groups into the
  similarity pass, so its similar list no longer repeats a line
  already reported as an exact/normalized leak via a duplicate line
  in the other file (e.g. two 20,000-line identical files now report
  1 leaked example instead of 20,001 — the same distinct example
  counted 20,001 times). Genuine paraphrase leaks are unaffected:
  full text and `--json` outputs on the bundled examples and on
  5,000-line templated/identical files are byte-identical to v0.2.3
  except for the two intended changes above.

### Verified, no change

The same round verified against the README and left the code alone
where behavior already matched: the similarity pass agrees with a
brute-force all-pairs oracle on 300 random trials, 200
duplicate-heavy stress trials, and 300 leakage-shaped trials
(cross-file reportable + normalized-hash groups); a lone-surrogate
escape (`"\ud800"`) in chat content passes `check`, `dedupe`
(stdout and `-o`), `split`, and `leakage --similarity` without
errors; `dedupe -o` with the output path equal to the input is safe
(the input is fully read before the output is opened); error paths
(directory or missing input for every subcommand, `--similarity`
outside (0, 1] including `nan`, negative `--max-tokens`,
`--val-ratio` outside [0, 1], unwritable output path) all exit 2
with a clean one-line message and no traceback; `split` with
`--val-ratio 0` / `1` writes a truly empty side; `leakage` of a file
against itself reports every line; stdin (`check -`) works. Two
observations recorded without a code change: `split` with
`--train-out` (or `--val-out`) equal to the input file overwrites
the input with that side's subset — the user explicitly named the
file as output, and only `--train-out` == `--val-out` is refused,
so treat an output path equal to the input as intentional; `check`
on an unreadable file prints "check FAILED" while exiting 2 (the
I/O-error code) — the wording is loose but the exit code is the
documented one.

## [0.2.3] - 2026-10-25

### Fixed

A documentation-vs-behavior and output-integrity QA round (replaying
every README example verbatim, diffing text output against `--json`
output, and re-running commands for identical results) found one defect
in `leakage`'s text output. Behavior on files with 20 or fewer leaks
per category is unchanged.

- **`leakage` text output silently dropped leaks past the 20th per
  category.** With 25 shared examples, only the first 20 `LEAK:` lines
  were printed and nothing said lines were omitted — the total line
  ("25 example(s) appear in both files") does not say *which* lines
  were cut, so a user fixing leaks from text output alone would miss
  the rest. This affected all three categories (exact, normalized-only,
  similar). Each truncated category now prints an explicit disclosure
  ("… and N more exact/normalized/similar leak(s) (see --json for the
  full list)"), matching the disclosure `check`'s issue lists already
  print ("… and N more errors"). The `--json` report was already
  complete and is unchanged.

### Verified, no change

The same round verified against the README and left the code alone
where behavior already matched: all captured README outputs reproduce
exactly (`check` on good/messy/similar, `dedupe`, `split`, `leakage`
with and without `--similarity`); text and `--json` reports agree on
counts, token statistics, line numbers and exit codes; `dedupe` and
`split` are byte-identical across repeat runs, splits are disjoint
with union equal to the input, and `dedupe` keeps the first
occurrence's original text; exit codes are 0/1/2 as documented
(clean / problems / usage-or-I/O error). Two observations recorded
without a code change: a 5,000-record heavily templated similarity
check takes ~20 s in-process on this VM versus the README's "~6 s"
(machine- and data-dependent estimate, and the result is correct);
`split` uses round-half-even, so 10 examples at `--val-ratio 0.25`
yields 2 validation examples (2.5 rounds to 2) — the ratio is
approximate by nature at small sizes, and determinism/disjointness
hold.

## [0.2.2] - 2026-10-23

### Fixed

A second, adversarial QA round (mutation fuzzing, property tests
against a brute-force oracle, and pathological hand-crafted inputs)
found six defects — all of them crashes or silent mis-validations on
inputs the first pass did not try. All are fixed; none of the fixes
changes behavior on well-formed datasets.

- **Deeply nested records crashed `check` with a RecursionError
  traceback** (the token walker and the value normalizer recurse per
  nesting level; a record nested ~1,000+ levels deep overflowed the
  interpreter stack, and `dedupe`/`split`/`leakage` had the same
  exposure through the parser). Line parsing is now total: values
  nested deeper than 100 levels are reported as a per-line error
  ("value is nested too deeply"), and parser-level recursion
  failures become the same error instead of a traceback.
- **Integer literals beyond Python's 4,300-digit limit crashed every
  command** with a raw `ValueError` traceback — the parse sites only
  caught `JSONDecodeError`. Such lines are now ordinary
  "invalid JSON" errors.
- **`NaN`, `Infinity` and `-Infinity` were accepted as valid JSON**
  (Python's parser allows them by default) and a record containing
  one validated cleanly. They are not valid JSON — strict parsers,
  including training APIs, reject them — and are now reported as
  invalid-JSON errors.
- **Strings containing lone surrogates** (e.g. from a `"\ud800"`
  escape) **crashed duplicate/leakage hashing** with a
  `UnicodeEncodeError`. Hashing now encodes with `surrogatepass`:
  deterministic, and distinct strings still hash distinctly.
- **A chat message whose `role` was an array or object crashed
  `check`** with `TypeError: unhashable type` in the role
  statistics counter. The invalid role is reported as before; the
  counter now files non-string roles under "?".
- **A content part with a non-string `text` value crashed `check`**
  with a `TypeError` in text extraction. It is now an explicit
  error ("content part N has non-string 'text'"), mirroring the
  v0.2.1 fix for non-string scalar content, and text extraction
  ignores non-string parts instead of crashing.

### Tests

- 11 new regression tests (88 total) covering every fix above,
  including a CLI sweep asserting no traceback and a documented
  exit code on a file combining all the pathological lines. All 11
  fail on the v0.2.1 code and pass on this release.
- Verified without code changes: a 600-trial property test of the
  similarity pass against brute-force Jaccard (exact agreement);
  a 300-file mutation fuzz over all commands (accounting and
  partition invariants hold); byte-for-byte dedupe/split output
  integrity on crafted cases; 100,000-line files check in ~31 s;
  2,000 all-near-duplicate records produce exactly 1,999 similarity
  warnings in ~4 s.

## [0.2.1] - 2026-10-23

### Fixed

- `check` on an unreadable file (missing path, directory, permission
  error) now exits with code 2, the documented I/O-error code, instead
  of 1 — CI can again distinguish "file could not be read" from
  "dataset has errors", in both text and `--json` modes.
- Records containing only one of `prompt` / `completion` are now
  treated as broken prompt/completion records and fail with the
  missing-key error, instead of being classified as "generic" and
  passing with only a warning.
- The `valid` count in `check` summaries no longer counts a record
  whose only error is the mixed-format error (`examples/messy.jsonl`
  now correctly reports 3 valid of 7; the README quoted the old,
  wrong count and has been corrected).
- Chat messages whose `content` is not a string or a list of content
  parts (e.g. a number, boolean, or object) are now errors instead of
  passing silently. `content: null` remains tolerated, as tool-call
  messages use it legitimately.
- `dedupe` and `split` summaries now report how many input lines were
  skipped as unparseable (invalid JSON, JSON arrays/scalars, invalid
  UTF-8) instead of dropping them silently.
- `dedupe`/`split` output now preserves each line's original text
  (only a CRLF carriage return is removed), as the README promises;
  previously surrounding whitespace was stripped.
- `split` rejects `--val-ratio` outside [0, 1] and identical
  `--train-out` / `--val-out` paths with a usage error (exit 2)
  instead of silently producing a nonsense split or overwriting the
  train output with the validation output. An empty split side is
  now written as a truly empty file instead of a single newline.
- `check` rejects a negative `--max-tokens` with a usage error
  (exit 2) instead of warning that every example exceeds a negative
  limit.
- "Line is not an object" errors now name JSON types (null, string,
  number, boolean, array) instead of Python type names (NoneType,
  str, bool, ...).

### Tests

- 17 new regression tests (77 total), one per fix above, including
  CLI end-to-end coverage of the exit codes. The pre-existing
  `test_check_missing_file_exit_2` now asserts the exit code its name
  always promised.

## [0.2.0] - 2026-10-23

### Added

- Text-similarity near-duplicate detection (`--similarity T`,
  0 < T ≤ 1), opt-in for `check` and `leakage`. Similarity is the
  Jaccard index of the texts' character 5-gram (shingle) sets over
  whitespace-collapsed, case-folded text — language-agnostic, so it
  behaves the same for unspaced scripts (Japanese, Chinese) as for
  spaced ones.
  - `check --similarity 0.8` warns about examples that are
    paraphrases or lightly edited copies of an earlier line, with
    both line numbers and the similarity score. Pairs already
    flagged as exact/normalized duplicates are suppressed by
    duplicate cluster and never double-reported; each example is
    reported once, against the earliest line it resembles.
  - `leakage --similarity 0.8` fails on paraphrase leakage across
    two files (a reworded validation example of a training example),
    in both text and `--json` output.
  - Candidate pairs are generated with a rarest-first prefix index
    plus a set-size filter (exact pruning), keeping the pass
    near-linear on real files: a synthetic 5,000-example file of
    heavily templated records checks in ~6 s.
  - `--similarity` outside (0, 1] is a usage error (exit 2).
- `examples/similar.jsonl`: two password-reset examples that are 91%
  similar with different wording, plus unrelated and distinct-topic
  controls.
- 30 new tests (60 total): shingle/Jaccard units including CJK and
  short texts, pair-finding semantics (threshold, skip pairs/groups,
  one-report rule, reportable predicate), `check` and `leakage`
  integration, and CLI end-to-end coverage of both flags.

## [0.1.0] - 2026-10-22

### Added

- `check` command: validation for chat-format and prompt/completion
  JSONL with a line number on every problem — invalid JSON, UTF-8 BOM,
  non-UTF-8 bytes, invalid roles, system message not first, empty
  content, conversations not ending with an assistant reply, mixed
  formats in one file.
- Dataset hygiene warnings: exact duplicates, near-duplicates
  (whitespace/case normalized), the same user prompt with conflicting
  assistant answers, consecutive user turns, and over-length examples
  (heuristic token estimate, `--max-tokens`).
- Per-file statistics: example counts and estimated-token distribution.
- `dedupe` command: removes exact duplicates, or exact + normalized
  duplicates with `--normalized`.
- `split` command: seeded, reproducible train/validation split, disjoint
  by construction.
- `leakage` command: fails if two files share any example, by exact or
  normalized hash.
- `--json` machine-readable reports for `check` and `leakage`.
- Bundled examples (`examples/good.jsonl`, `examples/messy.jsonl`,
  `examples/dupes.jsonl`) and a 30-test unittest suite.
