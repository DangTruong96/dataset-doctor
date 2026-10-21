# Security policy

## Supported versions

DatasetDoctor is pre-1.0. Security fixes are applied to the latest
release only; older releases do not receive backports.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Reporting a vulnerability

Please report vulnerabilities **privately** — do not open a public issue
for a security problem.

Use GitHub's private vulnerability reporting for this repository:
**Security → Advisories → Report a vulnerability** on
[github.com/DangTruong96/dataset-doctor](https://github.com/DangTruong96/dataset-doctor/security/advisories).

## Scope notes

DatasetDoctor runs entirely offline and only reads the files you point
it at. It never sends dataset contents anywhere. If you find a case
where parsing an untrusted JSONL file can do more than report errors
(crashes are bugs; code execution would be a vulnerability), please
report it through the channel above.
