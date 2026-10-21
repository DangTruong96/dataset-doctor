# DatasetDoctor

**Pre-flight checks for fine-tuning and evaluation JSONL datasets.**

`dataset-doctor` validates chat-format (`{"messages": [...]}`) and
prompt/completion JSONL files *before* you upload them — and, unlike the
training APIs, it tells you **which line** is broken. It also finds exact
and near-duplicate examples, conflicting answers to the same prompt, and
train/validation leakage, and it can dedupe and split a dataset
deterministically.

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

## Install

Requires Python 3.9+. There is nothing else to install.

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
examples/messy.jsonl — format: chat, 7 example(s), 4 valid, 7 error(s), 3 warning(s)
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

What `check` catches:

| Class | Examples |
| --- | --- |
| File level | UTF-8 BOM, non-UTF-8 bytes, empty file |
| Line level | invalid JSON (with column), line is not a JSON object, mixed formats in one file |
| Chat structure | missing/invalid role, system message not first, empty content, no user or no assistant message, conversation not ending with an assistant reply |
| Prompt/completion | missing keys, non-string or empty prompt |
| Dataset hygiene (warnings) | exact duplicates, near-duplicates (whitespace/case), same prompt with conflicting answers, consecutive user turns, over-length examples (estimated tokens over `--max-tokens`, default 4096) |

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

## Formats

- **Chat**: `{"messages": [{"role": "system"|"user"|"assistant"|"tool", "content": "..."}]}` —
  the format used by OpenAI fine-tuning and by open-model toolkits
  (Axolotl, LLaMA-Factory, Unsloth, TRL all consume the same shape).
- **Prompt/completion**: `{"prompt": "...", "completion": "..."}`.
- Anything else is reported as generic: JSON validity is checked, and you
  get a warning that no format rules were applied.

## Roadmap

- v0.2: preference/DPO format checks (`chosen`/`rejected`), per-role
  token breakdown, `--fix` mode for BOM and trailing-whitespace repair.
- v0.3: near-duplicate detection by text similarity (not just
  normalization), CSV/JSON-array import, HTML report.

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
