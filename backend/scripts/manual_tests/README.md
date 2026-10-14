# Manual test scripts

Ad-hoc scripts from earlier development. They talk to a **running server** (default
`http://localhost:8000`) or need sample files, so they are *not* part of the automated suite.
The automated tests live in `backend/tests/` and run with `pytest` (see the repo CI workflow).

Sample inputs are in `files/`. Some scripts reference the old locations of these files
(`test.pdf`, `test_files/...`); adjust the paths if you run them.
