# Changelog

All notable changes to DatasetDoctor are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

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
