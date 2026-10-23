# Changelog

All notable changes to DatasetDoctor are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

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
