## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## The failure it catches (new or changed checks only)

<!-- Every check in DatasetDoctor exists because a real dataset broke
     that way. Describe the incident or the provider error behind it. -->

## Checklist

- [ ] Runtime is still standard-library only
- [ ] Tests added or updated, and `python -m unittest discover -s tests -v` passes
- [ ] Exit codes unchanged: `0` clean, `1` problems found, `2` tool error
- [ ] Every problem is still reported with its line number
- [ ] README / examples updated if behaviour or flags changed
