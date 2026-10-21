# Contributing

Thanks for taking a look. DatasetDoctor is a small, single-file tool on
purpose — please help keep it that way.

## Ground rules

- **Runtime stays standard-library only.** No third-party dependencies;
  if a check needs a tokenizer or a network call, it does not belong in
  the core tool.
- **Every check needs a real failure behind it.** New checks are welcome
  when they catch a concrete way a training/eval file actually breaks —
  a rejected upload, a wasted training run, a leaked validation set.
  Describe the failure in the PR (a redacted example line or the
  provider's error message is perfect).
- **Every problem is reported with its line number.** That is the whole
  point of the tool; a check that cannot name the line is not ready.
- **Never require uploading data anywhere.** The tool runs fully offline.

## Development

```bash
git clone https://github.com/DangTruong96/dataset-doctor
cd dataset-doctor
python -m unittest discover -s tests -v   # all tests must pass
python dataset_doctor.py check examples/messy.jsonl   # should FAIL with line numbers
python dataset_doctor.py check examples/good.jsonl    # should pass
```

## Pull requests

- One change per PR, with tests for any parsing or rule change.
- Exit codes are part of the interface: `0` clean, `1` problems found,
  `2` usage or I/O error. Do not change them casually.
- If you add or change a rule, update the README table and CHANGELOG.
- Redact real training data in issues, tests and fixtures — synthetic
  examples with the same shape are always preferred.
