# Examples

Four small datasets that show what DatasetDoctor does. All outputs
below are real, captured from the commands shown.

## `good.jsonl` — a clean chat dataset

```bash
python dataset_doctor.py check examples/good.jsonl
```

```text
examples/good.jsonl — format: chat, 6 example(s), 6 valid, 0 error(s), 0 warning(s)
  estimated tokens: total 80, min 7, median 12.5, mean 13.3, max 20
check passed
```

## `messy.jsonl` — the classic defects

Contains, in order: a valid example; a truncated JSON line; an exact
duplicate; a conversation with no assistant reply; an invalid role
(`human`); an empty assistant message; a near-duplicate (extra spaces,
different case); and a prompt/completion record mixed into a chat file.

```bash
python dataset_doctor.py check examples/messy.jsonl   # exit code 1
```

Every problem is reported with its line number — see the full output in
the main [README](../README.md#usage).

## `dupes.jsonl` — duplicates for `dedupe`

Four lines: two unique examples, one exact duplicate, one duplicate that
differs only in spacing/case.

```bash
python dataset_doctor.py dedupe examples/dupes.jsonl              # removes 1
python dataset_doctor.py dedupe examples/dupes.jsonl --normalized # removes 2
```

## `similar.jsonl` — paraphrased near-duplicates

Four chat examples: a password-reset Q&A; the same Q&A with the
question reworded and one verb changed in the answer (91% similar by
character-shingle Jaccard — invisible to exact and normalized hashes);
an unrelated science example; and a same-domain but genuinely distinct
account question that stays below threshold.

```bash
python dataset_doctor.py check examples/similar.jsonl                    # no warnings
python dataset_doctor.py check examples/similar.jsonl --similarity 0.8   # flags line 2
```

Split lines 1 and 2+ across two files to see paraphrase leakage:
`leakage` passes without the flag and fails with `--similarity 0.8`.
