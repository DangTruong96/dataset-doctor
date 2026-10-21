# Self-evaluation — DatasetDoctor v0.1.0

Audit date: 2026-10-22 · Auditor: maintainer (self-audit before first
release). Rubric mirrors the credible-OSS checklist used for ShortsQC:
each row is PASS, FAIL (fixed before release), or PENDING-PUBLISH
(can only become true once the repository is public).

| # | Criterion | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | OSI-approved license file, correct holder/year | PASS | `LICENSE` — MIT, © 2026 DangTruong96 |
| 2 | Working code, CLI with `--help`, documented exit codes (0/1/2) | PASS | `dataset_doctor.py`; `--help` lists check/dedupe/split/leakage; exit codes exercised in tests |
| 3 | Automated tests exist and pass | PASS | 30 unittests, `python -m unittest discover -s tests` → OK (defect detection, dedupe/split/leakage, CLI end-to-end via subprocess) |
| 4 | End-to-end smoke test on realistic input | PASS | Bundled `examples/messy.jsonl` (truncated JSON, BOM-class defects, bad role, empty content, duplicates, mixed format) → `check` fails with the correct line numbers; `examples/good.jsonl` passes; dedupe→check and split→leakage flows verified end to end |
| 5 | Package installs cleanly | PASS | `pip install .` into a fresh venv; `dataset-doctor check examples/good.jsonl` passes and `dataset-doctor --version` prints 0.1.0 |
| 6 | CI configured (multi-version tests) | PASS (config) / PENDING-PUBLISH (first green run) | `.github/workflows/ci.yml` — Python 3.9–3.12 matrix + example smoke steps; first execution requires the public repo |
| 7 | README: what/why, install, usage with REAL captured output | PASS | README quotes verbatim terminal output captured 2026-10-22 from the bundled examples; market evidence for the problem is linked |
| 8 | Changelog + semantic versioning | PASS | `CHANGELOG.md` [0.1.0]; `pyproject.toml` version 0.1.0; git tag `v0.1.0` |
| 9 | Governance: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, maintainer named | PASS | All four files present; README "Maintainer & governance" names DangTruong96 as sole maintainer |
| 10 | Issue & PR templates | PASS | `.github/ISSUE_TEMPLATE/bug_report.md`, `feature_request.md`, `.github/pull_request_template.md` |
| 11 | No placeholders, fake badges, invented users/metrics | PASS | repo-wide grep for TODO/FIXME/lorem/placeholder/badge services → clean; README contains no star/user/download claims; token counts explicitly labelled heuristic estimates |
| 12 | Examples ship with the repo and are exercised by CI | PASS | `examples/{good,messy,dupes}.jsonl` + `examples/README.md`; CI smoke step runs them |
| 13 | Public repository, release page, topics | PENDING-PUBLISH | By design of this build phase: local only, nothing pushed |
| 14 | Honest scope limits documented | PASS | README states token counts are estimates, `tool` message structure is only partially validated (warning in code + README scope), and hosted-UI validation is acknowledged as an alternative for simple cases |

**Counts: 12 PASS · 1 PASS-with-PENDING part (CI first run) · 1
PENDING-PUBLISH (repo/release) · 0 FAIL.**

Known v0.1 limitations (disclosed, not hidden): heuristic token
estimation instead of a real tokenizer; near-duplicates are detected by
normalization, not semantic similarity; DPO/preference format is not yet
validated. All three are on the public roadmap in the README.
