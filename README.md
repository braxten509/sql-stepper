# SQL Stepper

Paste MySQL, then step through it like a debugger: clause by clause in the order MySQL runs it
(FROM, JOIN, WHERE, GROUP BY, HAVING, SELECT, DISTINCT, ORDER BY, LIMIT), into CTEs and subqueries,
and row by row for UPDATE and DELETE. Tables are shown at every step with changes highlighted.

Your code stays pinned on top with a number on each part in the order MySQL runs it. Below it is one
board where the same table is changed step by step: columns and values glide into place, a JOIN's
other table sits beside it and its values fly in, GROUP BY rows fold together, removed rows fade out.
Keys: left/right move between parts, up/down step (running on into the next part), Space plays,
Ctrl+Enter runs.

Run: `sql-stepper` (or `uv run app.py`). It opens http://127.0.0.1:8765.

First run downloads MySQL 8.0 (about 60 MB) into `~/.local/share/sql-stepper` and runs it privately
(socket only, no network port). It stops when the app stops. Each Run uses a throwaway database.

Check: `.venv/bin/python test_stepper.py` (or `uv run --with sqlglot==30.19.0 --with pymysql==1.2.3 test_stepper.py`).

## Website (sqlstepper.psbhr.com)

Runs on Google Cloud Run (project `forecaster-b7a86`, service `sqlstepper`, us-central1) from the
`Dockerfile`: the app plus its own MySQL, set up at build time. Every push to `main` on GitHub builds
it, runs the test inside it, and puts it live (`.github/workflows/deploy.yml`). Cloudflare points the
address at it (`cloudflare/`, deployed once with `npx wrangler deploy`).

Because anyone's SQL runs there, each Run gets its own database and a MySQL user that can only touch
that database, the whole run is stopped after 15 seconds, and there are limits on SQL size, runs per
visitor per minute, and runs at the same time.
