# Changelog

All notable changes to DatasetDoctor are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

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
