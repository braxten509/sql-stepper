# SQL Stepper

Paste MySQL and step through clause execution, CTEs, subqueries, and row-by-row UPDATE
and DELETE operations. The browser shows intermediate tables and highlights changes.
The backend is Python's `ThreadingHTTPServer`, with a private MySQL 8.0 server.

Keyboard: left/right switches clauses, up/down steps, Space plays, Ctrl+Enter runs SQL.

## Requirements

- Linux x86_64. Verified on CachyOS Linux with Python 3.12.13, uv 0.12.3 and Docker 29.8.1.
- Python >=3.10 as declared in the script metadata; Python 3.12 is the verified runtime.
  Older interpreters need a security-patched release providing tarfile extraction filters.
- uv for Python dependency resolution, and Docker for the container build.
- MySQL needs glibc, libaio (`libaio.so.1`) and libnuma. The Dockerfile installs
  `libaio1` and `libnuma1` on Debian Bookworm. On Arch/CachyOS, use `libaio` and `numactl`.
- Network access to the Python package index and MySQL CDN on first use. MySQL's
  first download is about 60 MB. A browser is needed for the interface.

## Setup

From a fresh checkout:

```sh
cd sql-stepper
uv python install 3.12
uv venv --python 3.12
uv pip install -r requirements-dev.txt
```

Run and test resolve their own exact runtime dependencies from inline script metadata.
No global `sql-stepper` executable is required. No secrets are required for SQL stepping.
The optional AI chat reads `AI_API_KEY`, `AI_URL` and `AI_MODEL` from the environment;
without a key it is disabled. The app does not automatically read `.env` files.

## Build, run and test

Run from the repository root:

```sh
uv run app.py
```

Opens http://127.0.0.1:8765. Stop with Ctrl+C. For a headless launch use
`NO_BROWSER=1 uv run app.py`; `HOST` and `PORT` override the bind address and port.
The server prints `SQL Stepper running at ...` when ready.

Run the real MySQL regression suite with one command:

```sh
uv run --with sqlglot==30.19.0 --with pymysql==1.2.3 test_stepper.py
```

Success prints `all good`; any failed assertion exits nonzero. The suite contains
21 assertions covering splitting, subqueries, CTEs, joins, grouping, window functions,
UPDATE, DELETE, UNION, functions and SQL errors. Each invocation creates a temporary
MySQL data directory and socket. It reuses cached MySQL binaries when available,
otherwise downloads them. Test data is removed after MySQL shuts down. It never
connects to or resets the normal app's database.

Build and verify the local container:

```sh
docker build -t sql-stepper:local .
docker run --rm sql-stepper:local python test_stepper.py
```

The artifact is the local image `sql-stepper:local`. To run it locally:

```sh
docker run --rm -p 127.0.0.1:8765:8765 sql-stepper:local
```

Open the same URL manually; Ctrl+C stops the container. The image includes Python
3.12, pinned Python dependencies and MySQL initialized during the build. These
commands do not deploy.

## Quality checks

Non-mutating checks, after setup:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Explicit formatting:

```sh
.venv/bin/ruff format .
```

`pyproject.toml` configures Python 3.10 syntax, line length 100 and E4/E7/E9/F/I rules.
Checks cover the app, test script and maintained Python mockup generator.

## Dependencies and local data

Runtime pins live in `app.py`, `test_stepper.py` and `Dockerfile`: sqlglot 30.19.0 and
PyMySQL 1.2.3. Development tooling is pinned in `requirements-dev.txt`. MySQL's exact
8.0.46 download URL is in `app.py`; the container base is `python:3.12-slim-bookworm`.
Keep matching pins together. [PSB-10](/PSB/issues/PSB-10) owns the dependency/advisory
review. Patch/minor upgrades require compatibility tests; major upgrades require a decision.

Normal runtime data lives at `${XDG_DATA_HOME:-~/.local/share}/sql-stepper`: downloaded
`mysql/` binaries, `data-ci/`, the socket, PID and log. Startup removes the legacy `data/`
scratch directory when starting a new server. Use a separate `XDG_DATA_HOME` if you
need a separate instance. Each SQL run creates and drops its own temporary database.

Repository-local `agentdb.rvf*`, `ruvector.db*`, Python caches, virtual environments,
logs and secrets are ignored. Existing local data stays on disk. No database fixtures
or generated artifacts belong in git.

## Known limitations

- The download targets Linux x86_64. Native macOS, Windows and ARM are unverified.
- Tests exercise real MySQL, so a first uncached run requires network and native libraries.
- The local HTTP launch is checked without opening a graphical browser; interactive UI
  verification is outside this tooling change.
- The existing `.github/workflows/deploy.yml` deploys to Google Cloud Run on pushes to
  `main`. It is separate from local checks. No push or deployment is part of this task.
  Existing routing configuration lives in `cloudflare/`.
- Dependency and container advisory status is tracked in [PSB-10](/PSB/issues/PSB-10),
  not implied by passing these regression checks. Standardization evidence is in
  [PSB-7](/PSB/issues/PSB-7).
