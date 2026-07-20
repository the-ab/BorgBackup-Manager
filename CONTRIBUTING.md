# Contributing to BorgBackup Manager

Thank you for helping improve the project.

## Before opening a change

- Use a public issue for normal bugs and feature proposals.
- Follow `SECURITY.md` for security-sensitive findings.
- Search existing issues and pull requests first.
- Keep changes focused and avoid unrelated formatting churn.
- Never include production data, credentials, private keys, databases or logs.

## Development setup

BorgBackup Manager targets Python 3.13 and the pinned dependencies in
`requirements.txt`.

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python -m pip install pytest==9.0.2 httpx==0.28.1 pytest-asyncio==1.4.0
python -m pytest -q
```

Also run the repository checks:

```bash
bash scripts/release-check.sh
```

## Pull requests

A pull request should:

- explain the problem and the implemented behavior;
- include or update regression tests;
- keep English default documentation and German `.de.md` documentation aligned;
- update release notes when behavior visible to users changes;
- preserve the fixed top-level release directory `BorgBackup-Manager/`;
- avoid database migrations unless they are necessary and documented;
- pass the local syntax checks and the complete automated test suite.

Substantial use of AI-assisted coding should be disclosed in the pull request.
AI-generated changes must be reviewed, adapted and tested by the contributor.

By submitting a contribution, you confirm that you have the right to provide it
and agree that it is licensed under the Apache License 2.0.
