# Contributing

Use Python 3.11+, type-safe changes, tests for failure modes, and no secret literals. Changes to artifact format, retention, crypto, restore, shell execution, access control, or deletion require security review and migration/rollback notes.

Run `py -m pytest` and `py -m ruff check backend` before submitting changes. Never add test credentials, artifact files, `.env`, or real database dumps to the repository.

