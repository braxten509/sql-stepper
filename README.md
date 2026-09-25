# SQL Stepper

Paste MySQL, then step through it like a debugger: clause by clause in the order MySQL runs it
(FROM, JOIN, WHERE, GROUP BY, HAVING, SELECT, DISTINCT, ORDER BY, LIMIT), into CTEs and subqueries,
and row by row for UPDATE and DELETE. Tables are shown at every step with changes highlighted.

Your code is shown with a number on each part in the order MySQL runs it. The current part opens
under its line and shows the tables. Keys: left/right move between parts, up/down step inside a
part (animated; press again to fast-forward), Space plays, Ctrl+Enter runs.

Run: `sql-stepper` (or `uv run app.py`). It opens http://127.0.0.1:8765.

First run downloads MySQL 8.0 (about 60 MB) into `~/.local/share/sql-stepper` and runs it privately
(socket only, no network port). It stops when the app stops. Each Run uses a throwaway database.

Check: `.venv/bin/python test_stepper.py` (or `uv run --with sqlglot==30.19.0 --with pymysql==1.2.3 test_stepper.py`).
