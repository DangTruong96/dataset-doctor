# DatasetDoctor

**Pre-flight checks for fine-tuning and evaluation JSONL datasets.**

`dataset-doctor` validates chat-format (`{"messages": [...]}`) and
prompt/completion JSONL files *before* you upload them — and, unlike the
training APIs, it tells you **which line** is broken. It also finds exact
and near-duplicate examples — including paraphrased copies that differ in
wording, via opt-in text-similarity detection — conflicting answers to
the same prompt, and train/validation leakage, and it can dedupe and
split a dataset deterministically.

Pure Python standard library. No dependencies, no network, no API keys —
your training data never leaves your machine.

## Why this exists

Fine-tuning file validation is a recurring public pain. OpenAI's forum is
full of threads where a job dies with *"The job failed due to an invalid
training file"* and no further detail — one user spent six hours hunting
a bad character in a 20,000-line file and begged the provider to *"give me
a line number, give me a character"*. The same failure classes keep
recurring: an example split across two lines, a UTF-8 BOM saved by a
Windows editor silently breaking the file, a conversation that doesn't
end with an assistant reply, the wrong role name.

Meanwhile the only "tooling" most people have is a sample script in a
cookbook, a generic JSONL normalizer that knows nothing about chat
format, or a website that asks you to paste proprietary training data
into a browser tab.

DatasetDoctor is the missing pre-flight check: run it in seconds, fix the
named lines, upload once.

## Requirements

- Python 3.9+
- No third-party dependencies — standard library only, nothing else to install.

## Install

```bash
# from a clone
git clone https://github.com/DangTruong96/dataset-doctor
cd dataset-doctor
python dataset_doctor.py --help        # run in place, or:
pip install .                          # installs the `dataset-doctor` command
```

## Usage

### `check` — validate a dataset

```bash
dataset-doctor check examples/good.jsonl
```

```text
examples/good.jsonl — format: chat, 6 example(s), 6 valid, 0 error(s), 0 warning(s)
  estimated tokens: total 80, min 7, median 12.5, mean 13.3, max 20
check passed
```

The bundled `examples/messy.jsonl` contains the classic defects. Real
output:

```bash
dataset-doctor check examples/messy.jsonl
```

```text
examples/messy.jsonl — format: chat, 7 example(s), 3 valid, 7 error(s), 3 warning(s)
  estimated tokens: total 57, min 4, median 8, mean 8.1, max 11
  errors:
  line 2: invalid JSON: Unterminated string starting at (column 43)
  line 4: conversation has no assistant message
  line 4: conversation does not end with an assistant message (last role: user) — SFT examples must end with the reply being taught
  line 5: message 1 has missing/invalid role 'human' (expected one of system, user, assistant, tool)
  line 5: conversation has no user message
  line 6: message 2 (assistant) has empty content
  line 8: record format (prompt-completion) differs from the file's format (chat) — mixed-format files are rejected by training APIs
  warnings:
  line 3: exact duplicate of line 1 — duplicates waste training budget and bias the model
  line 4: two consecutive user messages — usually a sign of a split example or a missing assistant reply
  line 7: near-duplicate of line 1 (identical after whitespace/case normalization)
check FAILED
```

Exit code is `1` when errors are found, `0` when clean, `2` for usage or
I/O errors — so it drops straight into CI:

```bash
dataset-doctor check data/train.jsonl || echo "dataset not ready"
dataset-doctor check data/train.jsonl --json   # machine-readable report
```

With `--similarity T` (0 < T ≤ 1), `check` adds a third duplicate
pass: examples whose **text** is at least T similar to an earlier line —
even with completely different wording — are flagged with both line
numbers and the similarity score. The bundled `examples/similar.jsonl`
holds two password-reset examples that share no exact or normalized
hash (one question is reworded, one verb in the answer changed). Real
output:

```bash
dataset-doctor check examples/similar.jsonl --similarity 0.8
```

```text
examples/similar.jsonl — format: chat, 4 example(s), 4 valid, 0 error(s), 1 warning(s)
  estimated tokens: total 252, min 52, median 63.5, mean 63, max 73
  warnings:
  line 2: text is 91% similar to line 1 — possible near-duplicate with different wording, which exact and normalized duplicate checks cannot see; paraphrased duplicates still bias training and inflate eval scores when they cross a split
check passed
```

Similarity is the Jaccard index of the texts' character 5-gram
("shingle") sets over whitespace-collapsed, case-folded text. Character
shingles — rather than word shingles — keep the measure identical for
unspaced scripts (Japanese, Chinese) and spaced ones. Each example is
reported once, against the earliest line it resembles, and pairs already
flagged as exact/normalized duplicates are never re-reported. Candidate
pairs come from a prefix index, so the pass stays fast on real files
(a synthetic 5,000-example file of heavily templated records checks in
~6 s). Start at `--similarity 0.8` and lower it toward 0.7 if you want
looser paraphrases too. It is off by default because it is a judgement
call, not an error.

What `check` catches:

| Class | Examples |
| --- | --- |
| File level | UTF-8 BOM, non-UTF-8 bytes, empty file |
| Line level | invalid JSON (with column), line is not a JSON object, mixed formats in one file |
| Chat structure | missing/invalid role, system message not first, empty content, no user or no assistant message, conversation not ending with an assistant reply |
| Prompt/completion | missing keys, non-string or empty prompt |
| Dataset hygiene (warnings) | exact duplicates, near-duplicates (whitespace/case), near-duplicates by text similarity (opt-in, `--similarity`), same prompt with conflicting answers, consecutive user turns, over-length examples (estimated tokens over `--max-tokens`, default 4096) |

Token counts are a **heuristic estimate** (~1 token per CJK character,
~4 characters per token otherwise) meant for spotting outliers — not a
billing number.

### `dedupe` — remove duplicate examples

```bash
dataset-doctor dedupe examples/dupes.jsonl --normalized -o clean.jsonl
# kept 2 example(s), removed 2 duplicate(s) → clean.jsonl
```

Without `--normalized`, only exact duplicates (same record, any key
order) are removed. With it, examples that differ only in whitespace or
capitalization are duplicates too. First occurrence wins; original line
text is preserved.

### `split` — train/validation split that cannot leak

```bash
dataset-doctor split examples/good.jsonl \
    --train-out /tmp/train.jsonl --val-out /tmp/val.jsonl --val-ratio 0.34
# split 6 example(s) → 4 train (/tmp/train.jsonl), 2 validation (/tmp/val.jsonl), seed 42
```

The shuffle is seeded (`--seed`, default 42), so the split is
reproducible, and the two outputs are disjoint by construction.

### `leakage` — prove two files share nothing

```bash
dataset-doctor leakage /tmp/train.jsonl /tmp/val.jsonl
# no leakage — the two files share no examples

dataset-doctor leakage /tmp/train.jsonl examples/good.jsonl
# LEAK: examples/good.jsonl line 1 is an exact duplicate of /tmp/train.jsonl line 1
# …
# leakage FAILED — 4 example(s) appear in both files   (exit code 1)
```

Leakage is checked by exact hash and by normalized hash (whitespace/case
insensitive), so a validation example that was lightly edited still
counts as leaked.

Add `--similarity T` and the check also fails on **paraphrase
leakage**: a validation example that is a reworded copy of a training
example — the case exact and normalized hashes structurally cannot
see. Splitting the first two lines of `examples/similar.jsonl` across
two files passes the plain check and fails with the flag:

```bash
dataset-doctor leakage /tmp/train.jsonl /tmp/val.jsonl
# no leakage — the two files share no examples

dataset-doctor leakage /tmp/train.jsonl /tmp/val.jsonl --similarity 0.8
# LEAK: /tmp/val.jsonl line 1 is 91% similar to /tmp/train.jsonl line 1 — possible paraphrase leakage
# leakage FAILED — 1 example(s) appear in both files   (exit code 1)
```

The similar pairs also appear in the `--json` report (with their
similarity scores), so CI can archive them.

## Formats

- **Chat**: `{"messages": [{"role": "system"|"user"|"assistant"|"tool", "content": "..."}]}` —
  the format used by OpenAI fine-tuning and by open-model toolkits
  (Axolotl, LLaMA-Factory, Unsloth, TRL all consume the same shape).
- **Prompt/completion**: `{"prompt": "...", "completion": "..."}`.
- Anything else is reported as generic: JSON validity is checked, and you
  get a warning that no format rules were applied.

## Roadmap

- v0.3: preference/DPO format checks (`chosen`/`rejected`), per-role
  token breakdown, `--fix` mode for BOM and trailing-whitespace repair.
- v0.4: CSV/JSON-array import, HTML report.

(Shipped in v0.2: near-duplicate detection by text similarity for
`check` and `leakage` — see `--similarity` above.)

## Maintainer & governance

DatasetDoctor is maintained by **DangTruong96** (sole maintainer):
decisions, releases and roadmap are made by the maintainer, versions
follow semantic versioning, and user-facing changes are recorded in
[CHANGELOG.md](CHANGELOG.md). Contributions are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md) and the
[code of conduct](CODE_OF_CONDUCT.md). Security reports: see
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE). © 2026 DangTruong96.
