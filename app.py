#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["sqlglot==30.19.0", "pymysql==1.2.3"]
# ///
"""SQL Stepper: paste MySQL code and step through how it runs, like a debugger.

Runs everything on a private MySQL 8.0 server (downloaded once into
~/.local/share/sql-stepper). Each run gets a throwaway database.
"""
import atexit
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pymysql
import sqlglot
from sqlglot import exp
from sqlglot.dialects.mysql import MySQL

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sql-stepper"
# data-ci: table names ignore case (lower_case_table_names=1), like LeetCode. MySQL only takes that
# setting when the data folder is created, so the old case-sensitive "data" folder is replaced.
BASE, DATA, SOCK = HOME / "mysql", HOME / "data-ci", HOME / "mysql.sock"
MYSQL_URL = "https://cdn.mysql.com/Downloads/MySQL-8.0/mysql-8.0.46-linux-glibc2.17-x86_64-minimal.tar.xz"
PORT = int(os.environ.get("PORT", 8765))
HOST = os.environ.get("HOST", "127.0.0.1")  # 0.0.0.0 inside a container
# Limits for a public site (anyone's SQL runs here)
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", 15))  # a whole run is stopped after this long
MAX_BODY = 200_000  # bytes of SQL per run
RUNS_PER_MINUTE = int(os.environ.get("RUNS_PER_MINUTE", 600))  # per IP; high because a whole class can share one school IP
TRUST_PROXY = bool(os.environ.get("TRUST_PROXY"))  # behind a proxy: the visitor is in X-Forwarded-For
MAX_STATEMENTS = 2000
# AI chat: any OpenAI-style chat API (OpenRouter by default). No key = no chat button.
AI_KEY = os.environ.get("AI_API_KEY", "")
AI_URL = os.environ.get("AI_URL", "https://openrouter.ai/api/v1/chat/completions")
AI_MODEL = os.environ.get("AI_MODEL", "z-ai/glm-5.3-flash")
# OpenRouter: only these US hosts, and only where chats are neither stored nor used for training
AI_HOSTS = os.environ.get("AI_HOSTS", "fireworks,together,baseten,deepinfra").split(",")
AI_NOTE = os.environ.get("AI_NOTE", "GLM 5.3 Flash on US servers that don't store or train on your chats.")
# The spending cap is the key's own daily limit at OpenRouter ($0.20), shared by everyone. No per-visitor
# limit: a class shares one school IP. When the cap is hit the server logs AI_BUDGET_REACHED, and a
# Google Cloud alert on that line emails the owner.
# Set on the website: chat only answers requests that came through the Cloudflare forwarder (which adds
# this secret), so nobody can call Cloud Run directly
PROXY_SECRET = os.environ.get("PROXY_SECRET", "")
SLOTS = threading.BoundedSemaphore(int(os.environ.get("MAX_PARALLEL", 4)))  # runs at the same time
MAX_ROWS = 300  # ponytail: display cap per table, raise if you step through big tables
MAX_ROW_STEPS = 12  # per-row steps shown for one UPDATE/DELETE


# ---------- MySQL server ----------

# MySQL 8's default sql_mode minus ONLY_FULL_GROUP_BY, which LeetCode also runs without
# (so "SELECT a, b ... GROUP BY a" works there and here).
SQL_MODE = "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"


def connect(user="root", password="", database=None):
    """root by default; a run connects as its own throwaway user that only sees its own database."""
    return pymysql.connect(unix_socket=str(SOCK), user=user, password=password, database=database,
                           autocommit=True, connect_timeout=2,
                           init_command=f"SET SESSION sql_mode = '{SQL_MODE}'")


def prepare_server():
    """Once at start: clear what a crashed run may have left behind."""
    with connect() as c, c.cursor() as cur:
        cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")  # for a server started with a binary log
        cur.execute(r"SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'step\_%'")
        for (db,) in cur.fetchall():
            cur.execute(f"DROP DATABASE `{db}`")
        cur.execute(r"SELECT user, host FROM mysql.user WHERE user LIKE 'step\_%'")
        for u, h in cur.fetchall():
            cur.execute(f"DROP USER '{u}'@'{h}'")


# small and quiet: no binary log (LeetCode-style functions need no DETERMINISTIC), no metrics,
# little memory, so it fits a small server
MYSQLD = ["--no-defaults", "--lower-case-table-names=1", "--disable-log-bin", "--performance-schema=OFF",
          "--innodb-buffer-pool-size=64M", "--innodb-redo-log-capacity=8M", "--max-connections=60",
          "--skip-name-resolve", "--mysqlx=OFF", "--skip-networking"]


def install():
    """Download MySQL and create its data folder, once (a Docker build runs just this)."""
    if not BASE.exists():
        print("Downloading MySQL 8.0 (one time, about 60 MB)...", flush=True)
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = HOME / "mysql.tar.xz"
        urllib.request.urlretrieve(MYSQL_URL, tmp)
        with tarfile.open(tmp) as t:
            t.extractall(HOME, filter="data")
        tmp.unlink()
        next(HOME.glob("mysql-8.0.*")).rename(BASE)
    if not DATA.exists():
        print("Setting up MySQL data folder (one time)...", flush=True)
        subprocess.run([str(BASE / "bin/mysqld"), *MYSQLD, f"--basedir={BASE}", f"--datadir={DATA}",
                        "--initialize-insecure"], check=True, capture_output=True)


def start_mysql():
    try:
        with connect() as c, c.cursor() as cur:  # already running (left over from a previous session)
            cur.execute("SELECT @@lower_case_table_names")
            if cur.fetchone()[0] == 1:
                return prepare_server()
            cur.execute("SHUTDOWN")  # an old case-sensitive server: replace it
        time.sleep(2)
    except pymysql.err.OperationalError:
        pass
    shutil.rmtree(HOME / "data", ignore_errors=True)  # the old case-sensitive folder (only scratch databases)
    install()
    proc = subprocess.Popen([str(BASE / "bin/mysqld"), *MYSQLD, f"--basedir={BASE}", f"--datadir={DATA}",
                             f"--socket={SOCK}", f"--pid-file={HOME / 'mysqld.pid'}", f"--log-error={HOME / 'mysqld.log'}"])
    atexit.register(proc.terminate)
    for _ in range(160):
        if proc.poll() is not None:
            break
        try:
            connect().close()
            return prepare_server()
        except pymysql.err.OperationalError:
            time.sleep(0.25)
    sys.exit(f"MySQL failed to start. See {HOME / 'mysqld.log'}")


# ---------- Splitting pasted SQL into statements ----------

STMT_START = re.compile(r"\s*(select|with|insert|update|delete|create|drop|alter|truncate|replace)\b", re.I)


PROGRAM = re.compile(r"\s*create\s+(?:definer\s*=\s*\S+\s+)?(function|procedure|trigger)\s+`?(\w+)`?", re.I)


def blocks(sql):
    """Inside CREATE FUNCTION/PROCEDURE/TRIGGER: how many BEGIN (or CASE) blocks are still open at the end,
    and where the outermost one closed (its ; end inner statements, not the CREATE)."""
    if not PROGRAM.match(sql):
        return 0, None
    depth, closed = 0, None
    blank = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`", lambda m: " " * len(m.group()), sql)
    for m in re.finditer(r"\b(begin|case|end)\b(\s+(?:if|while|loop|repeat)\b)?", blank, re.I):
        depth += 1 if m.group(1).lower() in ("begin", "case") else -1 if not m.group(2) else 0
        if depth == 0 and closed is None and m.group(1).lower() == "end":
            closed = m.end()
    return depth, closed


def split_semicolons(text):
    """Split on ; outside quotes (and outside a stored program's BEGIN ... END), dropping comments."""
    parts, buf, q, i = [], [], None, 0
    while i < len(text):
        c = text[i]
        if q:
            if c == "\\":
                buf.append(text[i:i + 2])
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"`":
            q = c
        elif c == ";" and blocks("".join(buf))[0] > 0:
            pass  # kept below: it ends a statement inside the body
        elif c == ";":
            parts.append("".join(buf))
            buf, i = [], i + 1
            continue
        elif text.startswith("-- ", i) or text.startswith("--\n", i) or c == "#":
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            i = len(text) if j < 0 else j + 2
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parses(sql):
    try:
        sqlglot.parse_one(sql, read="mysql")
        return True
    except sqlglot.errors.SqlglotError:
        return False


def split_sql(text):
    """Semicolons, or LeetCode style: one statement per line with no semicolons.
    A new statement starts at a line beginning with a statement keyword, but only
    if everything before it already parses as a complete statement."""
    out = []
    for chunk in split_semicolons(text):
        if PROGRAM.match(chunk):  # a function's body has lines like "select ..." that are not new statements
            end = blocks(chunk)[1] or len(chunk)
            out.append(chunk[:end].strip())
            chunk = chunk[end:]
        cur = []
        for line in chunk.split("\n"):
            if cur and STMT_START.match(line) and parses("\n".join(cur)):
                out.append("\n".join(cur).strip())
                cur = []
            cur.append(line)
        if "\n".join(cur).strip():
            out.append("\n".join(cur).strip())
    return out


# ---------- Table views sent to the browser ----------

def cell(v):
    if v is None or isinstance(v, (int, float, str)):
        return v
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode()
        except UnicodeDecodeError:
            return "0x" + v.hex()
    return str(v)  # Decimal, date, datetime, timedelta


def view(name, cols, rows, marks=None, olds=None, groups=None, badge=None):
    out = []
    for i, r in enumerate(rows[:MAX_ROWS]):
        row = {"v": [cell(x) for x in r]}
        if marks and marks[i]:
            row["m"] = marks[i]
        if olds and olds.get(i):
            row["old"] = {c: cell(v) for c, v in olds[i].items()}
        if groups:
            row["g"] = groups[i]
        out.append(row)
    return {"name": name, "badge": badge, "cols": list(cols), "rows": out, "more": max(0, len(rows) - MAX_ROWS)}


def diff(before, after):
    """Compare two snapshots {table: (cols, rows)} and mark what changed."""
    views = []
    for name, (cols, rows) in after.items():
        if name not in before:
            views.append(view(name, cols, rows, ["added"] * len(rows), badge="new table"))
            continue
        bcols, brows = before[name]
        if (bcols, brows) == (cols, rows):
            views.append(view(name, cols, rows))
        elif bcols != cols:
            views.append(view(name, cols, rows, badge="structure changed"))
        elif len(brows) == len(rows):  # same row count: compare in place (UPDATE)
            olds = {i: {c: o for c, (o, n) in enumerate(zip(br, r)) if o != n}
                    for i, (br, r) in enumerate(zip(brows, rows)) if br != r}
            views.append(view(name, cols, rows, ["changed" if i in olds else None for i in range(len(rows))],
                              olds, badge="changed"))
        else:  # rows added and/or removed
            have = Counter(brows)
            marks = []
            for r in rows:
                marks.append(None if have[r] > 0 else "added")
                have[r] -= 1
            keep, gone = Counter(rows), []
            for r in brows:
                if keep[r] > 0:
                    keep[r] -= 1
                else:
                    gone.append(r)
            views.append(view(name, cols, rows + gone, marks + ["removed"] * len(gone), badge="changed"))
    for name, (cols, rows) in before.items():
        if name not in after:
            views.append(view(name, cols, rows, ["removed"] * len(rows), badge="dropped"))
    views.sort(key=lambda v: v["badge"] is None)  # changed tables first
    return views


# ---------- Stepping ----------

def with_sql(ctes):
    if not ctes:
        return ""
    rec = any(c.parent is not None and c.parent.args.get("recursive") for c in ctes)
    return "WITH " + ("RECURSIVE " if rec else "") + ", ".join(c.sql("mysql") for c in ctes) + " "


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


# sqlglot writes a DIV b as CAST(a / b AS SIGNED), which rounds where DIV truncates: keep DIV
MySQL.Generator.TRANSFORMS[exp.IntDiv] = lambda g, e: f"{g.sql(e, 'this')} DIV {g.sql(e, 'expression')}"

# A calculation, piece by piece: LEAF pieces are values read as they are (a column, an aggregate, a window,
# a subquery, a CASE); any other function or operator is a step worked out from its pieces.
LEAF = (exp.Column, exp.AggFunc, exp.Window, exp.Subquery, exp.Case, exp.If)
NO_FRAME = {"ROW_NUMBER", "RANK", "DENSE_RANK", "PERCENT_RANK", "CUME_DIST", "NTILE", "LAG", "LEAD"}  # the rest read a frame


def fname(e, text=""):
    """A function's name as the user wrote it (IFNULL, BIT_OR), not sqlglot's (COALESCE, BITWISE_OR_AGG)."""
    m = e.meta
    if "start" in m and text and re.fullmatch(r"\w+", text[m["start"]:m["end"] + 1]):
        return text[m["start"]:m["end"] + 1].upper()
    return e.name.upper() if isinstance(e, exp.Anonymous) else e.sql_name()


def as_written(e, text=""):
    """An expression's SQL with function names as the user wrote them."""
    out = e.sql("mysql")
    for f in e.find_all(exp.Func):
        if fname(f, text) != f.sql_name():
            out = out.replace(f.sql_name() + "(", fname(f, text) + "(", 1)
    return out


def unwrap(e):
    """(x) and sqlglot's hidden type wrappers (YEAR(d) holds d inside one) show as x."""
    while True:
        kids = list(e.iter_expressions())
        hidden = type(e).__name__.startswith("TsOrDs") or (len(kids) == 1 and not isinstance(e, LEAF) and e.sql("mysql") == kids[0].sql("mysql"))
        if isinstance(e, exp.Paren) or hidden:
            e = kids[0]
        else:
            return e


def is_step(e):
    # a constant like -1 stays as text; NOW() and friends still count (their value changes)
    return isinstance(e, (exp.Func, exp.Binary, exp.Unary, exp.In, exp.Between)) and not isinstance(e, LEAF + (exp.Paren,)) \
        and (e.find(*LEAF) is not None or (isinstance(e, exp.Func) and not list(e.iter_expressions())))


def calc_steps(top, text, ref):
    """Each step of a calculation, innermost first: its text with its pieces as __A0__, __A1__... (ref gives
    the extra column that holds each piece's value per row), and where its own value is."""
    steps = []

    def visit(e):
        e = unwrap(e)
        if not is_step(e) or len(steps) >= 20:  # ponytail: 20 steps per column; a longer formula shows its first 20
            return
        for c in e.iter_expressions():
            visit(c)
        c, args = e.copy(), []
        for orig, cp in zip(list(e.iter_expressions()), list(c.iter_expressions())):
            b = unwrap(orig)
            if isinstance(b, LEAF) or is_step(b):
                cp.replace(exp.Var(this=f"__A{len(args)}__"))
                args.append(ref(b.sql("mysql")))
        tpl = c.sql("mysql")
        if isinstance(e, exp.Func) and tpl.upper().startswith(e.sql_name() + "("):  # IFNULL, not the COALESCE sqlglot writes
            tpl = fname(e, text) + tpl[len(e.sql_name()):]
        steps.append({"tpl": tpl, "args": args, "at": ref(e.sql("mysql"))})

    visit(top)
    return steps


def agg_info(a, ref, text=""):
    """What goes into an aggregate: the value it reads from each row (none for COUNT(*)), and DISTINCT."""
    this = a.this
    if isinstance(this, exp.Order):  # GROUP_CONCAT(x ORDER BY y)
        this = this.this
    d = {"sql": a.sql("mysql"), "fn": fname(a, text), "distinct": isinstance(this, exp.Distinct)}
    if isinstance(this, exp.Distinct):
        this = this.expressions[0]  # ponytail: COUNT(DISTINCT a, b) shows a only
    if isinstance(this, exp.Expression) and not isinstance(this, exp.Star):
        d["arg"], d["at"] = as_written(this, text), ref(this.sql("mysql"))
    return d


def top_aggs(exprs):
    """The aggregates in these expressions (not the ones inside a window or a subquery), by their SQL."""
    return {a.sql("mysql"): a for e in exprs for a in e.find_all(exp.AggFunc)
            if not a.find_ancestor(exp.Window, exp.Subquery)}


def inline_window(w, defs):
    """OVER w / OVER (w ROWS ...) with the WINDOW clause filled in, so it can be run and replayed on its own."""
    name = w.args.get("alias")
    if not name:
        return w
    base = defs.get(name.name if isinstance(name, exp.Expression) else str(name))
    if base is None:
        return None
    base = inline_window(base, defs)
    if base is None:
        return None
    pick = lambda k: w.args.get(k) or base.args.get(k)
    return exp.Window(this=w.this.copy(), partition_by=[p.copy() for p in pick("partition_by") or []],
                      order=pick("order").copy() if pick("order") else None, spec=pick("spec").copy() if pick("spec") else None)


def inline_windows(node):
    """Spell every OVER w out from its WINDOW clause (sqlglot writes WINDOW w2 AS (w) back wrong, so every
    query the stepper builds from this one would fail). The page still points at what the user wrote."""
    for sel in list(node.find_all(exp.Select)):
        defs = {wd.this.name if isinstance(wd.this, exp.Expression) else str(wd.this): wd for wd in sel.args.get("windows") or []}
        if not defs:
            continue
        for w in list(sel.find_all(exp.Window)):
            full = inline_window(w, defs) if w.args.get("alias") and w.find_ancestor(exp.Select) is sel else None
            if full is not None:
                full.meta["shown"] = w.sql("mysql")
                w.replace(full)
        sel.set("windows", None)


def window_detail(w, ref, shown=None, text=""):
    """What the page needs to replay a window function: each row's partition and place in the sorted
    order, the value it reads, and (for functions that read a frame) the last row of its frame and its size."""
    f = w.this
    part = [p.sql("mysql") for p in w.args.get("partition_by") or []]
    order = w.args.get("order")
    ords = order.expressions if order else []
    over = (f"PARTITION BY {', '.join(part)} " if part else "") + (f"ORDER BY {', '.join(o.sql('mysql') for o in ords)}" if ords else "")
    d = {"fn": fname(f, text), "sql": shown or w.sql("mysql"),
         "part": part, "order": [{"sql": o.this.sql("mysql"), "desc": bool(o.args.get("desc"))} for o in ords],
         "spec": w.args["spec"].sql("mysql") if w.args.get("spec") else None,
         "res": ref(w.sql("mysql")), "pos": ref(f"ROW_NUMBER() OVER ({over})"),
         "pvals": [ref(p) for p in part], "ovals": [ref(o.this.sql("mysql")) for o in ords]}
    if part:
        d["pid"] = ref(f"DENSE_RANK() OVER (ORDER BY {', '.join(part)})")
    this = f.args.get("this")
    if d["fn"] == "NTILE":
        d["n"] = this.sql("mysql")
    elif isinstance(this, exp.Expression) and not isinstance(this, (exp.Star, exp.Literal)):
        d["argsql"], d["arg"] = this.sql("mysql"), ref(this.sql("mysql"))
    for k in ("offset", "default"):
        if isinstance(f.args.get(k), exp.Expression):
            d[k] = f.args[k].sql("mysql")
    if d["fn"] not in NO_FRAME:  # the frame: COUNT(*) over it is its size; counted from the start it ends at the last row
        cnt = w.copy()
        cnt.set("this", exp.Count(this=exp.Star()))
        d["size"] = ref(cnt.sql("mysql"))
        spec = cnt.args.get("spec")
        if spec:
            spec.set("start", "UNBOUNDED")
            spec.set("start_side", "PRECEDING")
        d["hi"] = ref(cnt.sql("mysql"))
    return d


COMPARE = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.NullSafeEQ, exp.Is)


def checks(cond, text=""):
    """Split a condition into its simple checks (one AND or OR chain) so each row can show its own values.
    Returns (detail, extra SELECT columns). Per check the extra columns are: its truth, then the left
    value, then the right value (the values only for comparisons)."""
    kind = exp.And if isinstance(cond, exp.And) else exp.Or if isinstance(cond, exp.Or) else None
    leaves = []

    def walk(e):
        if kind and isinstance(e, kind):
            walk(e.this)
            walk(e.expression)
        else:
            leaves.append(e)
    walk(cond)
    out, cols, tail = [], [], []

    def ref(sql):  # values the calculation steps read go after the checks' own columns
        tail.append(f"({sql})")
        return len(tail) - 1
    for p in leaves:
        core, d = p.unnest(), {"sql": p.sql("mysql")}
        cols.append(f"({d['sql']})")
        if isinstance(core, COMPARE + (exp.In, exp.Between)):
            full, left = core.sql("mysql"), core.this.sql("mysql")
            d["left"] = left
            cols.append(f"({left})")
            right = core.expression.sql("mysql") if isinstance(core, COMPARE) and core.expression else None
            if right and full.startswith(left) and full.endswith(right) and not core.expression.find(exp.Query):
                d["right"], d["op"] = right, full[len(left):len(full) - len(right)].strip()
                cols.append(f"({right})")
            else:
                d["rest"] = full[len(left):].strip()  # e.g. "IN (SELECT p_id FROM Tree)"
                if isinstance(core, exp.In) and core.args.get("query"):
                    d["query"] = core.args["query"].unnest().sql("mysql")  # Stepper.fill_lists runs it
            # YEAR(d) = 2020: also show how YEAR(d) came out
            sides = [core.this] + ([core.expression] if isinstance(core, COMPARE) and core.expression else [])
            calc = [st for side in sides for st in calc_steps(side, text, ref)]
            if calc:
                d["calc"] = calc
        out.append(d)
    for d in out:  # tail positions count from the first check column
        for st in d.get("calc", []):
            st["args"], st["at"] = [a + len(cols) for a in st["args"]], st["at"] + len(cols)
    return {"combine": kind.key.upper() if kind else None, "checks": out}, cols + tail


def owner_query(node):
    p = node.parent
    while p is not None and not isinstance(p, exp.Query):
        p = p.parent
    return p


class Stepper:
    def __init__(self, cur):
        self.cur, self.steps, self.text, self.funcs = cur, [], "", {}

    def run(self, sql):
        self.cur.execute(sql)
        cols = [d[0] for d in self.cur.description or []]
        return cols, [tuple(r) for r in self.cur.fetchall()]

    def add(self, stmt, title, explain, kind="query", scope="", tables=(), sql=None):
        self.steps.append({"stmt": stmt, "title": title, "explain": explain, "kind": kind,
                           "scope": scope, "tables": list(tables), "sql": sql})

    def snapshot(self):
        _, names = self.run("SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = DATABASE() ORDER BY create_time, table_name")
        return {n: self.run(f"SELECT * FROM `{n}`") for (n,) in names}

    # --- one top-level statement ---

    def statement(self, text, i):
        self.text = text  # parsed nodes point into this (function names as the user wrote them)
        prog = PROGRAM.match(text)
        if prog:
            self.cur.execute(text)
            kind, name = prog.group(1).upper(), prog.group(2)
            m = re.match(r"\s*\(([^)]*)\)[\s\S]*?\bbegin\b([\s\S]*)\bend\b\s*$", text[prog.end():], re.I)
            if kind == "FUNCTION" and m:
                params = [p.split()[0].strip("`") for p in m.group(1).split(",") if p.strip()]
                self.funcs[name.lower()] = {"name": name, "params": params, "body": m.group(2), "stmt": i}
            self.add(i, f"CREATE {kind} {name}", f"Made {kind.lower()} {name}. It runs when it gets called.", kind="change")
            return
        try:
            node = sqlglot.parse_one(text, read="mysql")
        except sqlglot.errors.SqlglotError:
            node = None
        if node is not None:
            inline_windows(node)
        if isinstance(node, exp.Query):
            self.run(text)  # real error? fail here, before any previews
            for f in node.find_all(exp.Anonymous):  # SELECT getNth(2): step inside the function first
                if f.name.lower() in self.funcs and all(isinstance(a, exp.Literal) for a in f.expressions):
                    self.replay(self.funcs[f.name.lower()], [a.sql("mysql") for a in f.expressions])
                    self.text = text
            self.query(node, [], "", i, raw=text)
            return
        if isinstance(node, exp.Insert) and isinstance(node.expression, exp.Query):
            self.query(node.expression, [], "SELECT inside INSERT", i)
        plan = None
        if isinstance(node, (exp.Update, exp.Delete)):
            try:
                plan = self.find_rows(node)
            except (pymysql.MySQLError, sqlglot.errors.SqlglotError, KeyError, IndexError):
                pass  # preview only; the real statement below reports any real error
        after = self.change(text, node, i)
        if plan:  # row-by-row steps go before the final change step
            final = self.steps.pop()
            self.row_steps(node, i, plan, after)
            self.steps.append(final)

    def change(self, text, node, i):
        before = self.snapshot()
        self.cur.execute(text)
        n = self.cur.rowcount
        after = self.snapshot()
        tbl = node.this if isinstance(node, (exp.Update, exp.Delete)) and isinstance(node.this, exp.Table) else \
            node.find(exp.Table) if node else None  # DELETE p1 FROM Person p1: name the real table
        t = tbl.name.lower() if tbl else "the table"  # lower_case_table_names=1 stores names lowercased
        if isinstance(node, exp.Insert):
            msg = f"INSERT added {plural(n, 'row')} to {t}. New rows are green."
        elif isinstance(node, exp.Update):
            msg = (f"UPDATE changed {plural(n, 'row')} in {t}. Changed cells are amber with the old value crossed out. "
                   "(MySQL only counts rows whose values actually changed.)")
        elif isinstance(node, exp.Delete):
            msg = f"DELETE removed {plural(n, 'row')} from {t}. Removed rows are shown in red."
        elif isinstance(node, exp.Create):
            msg = (f"{t} already existed, so IF NOT EXISTS skipped this." if tbl and t in before
                   else f"CREATE made a new {'view' if node.kind == 'VIEW' else 'empty table'} named {t}.")
        elif isinstance(node, exp.TruncateTable):
            gone = len(before.get(t, ((), ()))[1])
            msg = f"TRUNCATE emptied {t} ({plural(gone, 'row')} removed). Unlike DELETE it can't be filtered with WHERE."
        elif isinstance(node, exp.Drop):
            msg = f"DROP deleted {t} and everything in it."
        elif isinstance(node, exp.Alter):
            msg = f"ALTER TABLE changed the structure of {t}."
        else:
            msg = f"Statement ran. MySQL reports {plural(max(n, 0), 'row')} affected."
        title = re.sub(r"\s+", " ", text)
        self.add(i, title[:80] + ("…" if len(title) > 80 else ""), msg, kind="change", tables=diff(before, after))
        return after

    # --- a stored function, stepped through with real values ---

    def replay(self, f, args, auto=False):
        """Call a function the way LeetCode does: each SET with its values, then the RETURN query stepped
        through like any other query (the parameters filled in), then the real call's result."""
        i = f["stmt"]  # the steps point into the function's code, even when a later query calls it
        call = f"{f['name']}({', '.join(args)})"
        scope = f"inside {call}"
        env = dict(zip((p.lower() for p in f["params"]), args))  # name -> SQL literal

        def lit(x):
            return "NULL" if x is None else str(x) if isinstance(x, (int, float)) else "'" + str(x).replace("'", "''") + "'"

        def bind(sql):  # a parameter or variable wins over a column with the same name, as in MySQL
            return sqlglot.parse_one(sql, read="mysql").transform(
                lambda x: sqlglot.parse_one(env[x.name.lower()], read="mysql")
                if isinstance(x, exp.Column) and not x.table and x.name.lower() in env else x)

        def value(sql):
            return self.run(f"SELECT {sql}")[1][0][0]
        self.add(i, f"Call {call}", "LeetCode calls your function with its own test values." if auto else f"The query calls {call}.",
                 kind="note", scope=scope, sql=call)
        self.steps[-1]["detail"] = {"type": "set", "call": True, "auto": auto,
                                    "vars": [{"name": p, "after": cell(value(a))} for p, a in zip(f["params"], args)]}
        for part in split_semicolons(f["body"]):
            d, st, r = re.match(r"declare\s+([\w\s,]+?)\s+\w+(?:\([^)]*\))?(?:\s+default\s+([\s\S]+))?$", part, re.I), \
                re.match(r"set\s+`?(\w+)`?\s*=\s*([\s\S]+)$", part, re.I), re.match(r"return\b([\s\S]+)$", part, re.I)
            if d:
                for x in d.group(1).split(","):
                    env[x.strip().lower()] = lit(value(bind(d.group(2)).sql("mysql"))) if d.group(2) else "NULL"
            elif st:
                name, before = st.group(1), env.get(st.group(1).lower(), "NULL")
                env[name.lower()] = lit(value(bind(st.group(2)).sql("mysql")))
                self.add(i, part, f"{name} changes.", kind="note", scope=scope, sql=part)
                self.steps[-1]["detail"] = {"type": "set", "vars": [{"name": name, "before": cell(value(before)), "after": cell(value(env[name.lower()]))}]}
            elif r:
                node, text = bind(r.group(1)), self.text
                if isinstance(node, exp.Subquery) and isinstance(node.unnest(), exp.Query):
                    self.text = r.group(1)  # function names in the RETURN query point into this text
                    self.query(node, [], scope, i)
                    self.text = text
                break
            else:  # IF, loops, SELECT INTO ...: run it, but show only the answer
                self.add(i, part[:60], "This part of the function isn't stepped through; the result below is the real answer.",
                         kind="note", scope=scope)
                break
        if auto:  # a query that calls it shows the answer itself
            cols, rows = self.run(f"SELECT {call}")
            self.add(i, f"{call} returns", f"{call} returns {cell(rows[0][0]) if rows and rows[0][0] is not None else 'NULL'}. "
                     f"To try another value, add a line like SELECT {f['name']}({', '.join('2' for _ in args)}); to your code.",
                     kind="result", tables=[view(call, [call], rows)])

    # --- UPDATE / DELETE, one row at a time ---

    def find_rows(self, node):
        """Before running an UPDATE/DELETE: which rows of the target table will it touch?"""
        this = node.this
        sources = [this] + [j.this for j in this.args.get("joins") or []]
        real = {s.alias_or_name.lower(): s.name.lower() for s in sources if isinstance(s, exp.Table)}  # names ignore case
        if isinstance(node, exp.Update):
            target = node.expressions[0].this.table or this.alias_or_name
        else:
            target = node.args["tables"][0].alias_or_name if node.args.get("tables") else this.alias_or_name
        table = real[target.lower()]
        cols, brows = self.snapshot()[table]
        tail = " ".join(node.args[k].sql("mysql") for k in ("where", "order", "limit") if node.args.get(k))
        _, found = self.run(f"SELECT {'DISTINCT ' if len(sources) > 1 else ''}`{target}`.* FROM {this.sql('mysql')} {tail}")
        used, positions = set(), []
        for r in found:
            pos = next((p for p, b in enumerate(brows) if p not in used and b == r), None)
            if pos is None:
                return None  # can't line rows up (e.g. table too big to show); skip the preview
            used.add(pos)
            positions.append(pos)
        det, where = None, node.args.get("where")
        if where and len(sources) == 1 and not node.args.get("limit"):
            det, pcols = checks(where.this, self.text)
            self.fill_lists(det, "")
            _, rows2 = self.run(f"SELECT `{target}`.*, {', '.join(pcols)} FROM {this.sql('mysql')}")
            if [r[:len(cols)] for r in rows2] == brows:  # same row order as the snapshot, so they line up
                det.update(type="filter", rows=[[cell(x) for x in r[len(cols):]] for r in rows2[:MAX_ROWS]])
            else:
                det = None
        return table, cols, brows, positions, det

    def row_steps(self, node, i, plan, after):
        table, cols, brows, positions, det = plan
        is_update = isinstance(node, exp.Update)
        scope = f"{node.key.upper()} row by row"
        where = node.args.get("where")
        cond = f" {where.sql('mysql')}" if where else ", with no WHERE, so every row"
        head = (f"First MySQL finds the rows to {'update' if is_update else 'delete'}:{cond}. "
                f"{len(positions)} of {plural(len(brows), 'row')} in {table} match (blue).")
        marks = [None] * len(brows)
        for pos in positions:
            marks[pos] = "match"
        self.add(i, where.sql("mysql") if where else f"Find rows to {'update' if is_update else 'delete'}",
                 head + ("" if positions else " Nothing will change."),
                 scope=scope, tables=[view(table, cols, brows, marks)], sql=where.sql("mysql") if where else None)
        if det:
            self.steps[-1]["detail"] = det
        # UPDATE keeps row order, so the real after-state lines up with the before-state by position.
        # ponytail: an UPDATE that changes a primary key can reorder rows; the per-row view would then be off.
        acols, arows = after.get(table, (None, []))
        if is_update and (acols != cols or len(arows) != len(brows)):
            return
        rows, olds, marks = list(brows), {}, [None] * len(brows)
        for k, pos in enumerate(positions[:MAX_ROW_STEPS]):
            marks = [("changed" if is_update else "removed") if m == "current" else m for m in marks]
            marks[pos] = "current"
            if is_update:
                ch = {c: o for c, (o, n) in enumerate(zip(rows[pos], arows[pos])) if o != n}
                rows[pos] = arows[pos]
                if ch:
                    olds[pos] = ch
                what = ", ".join(f"{cols[c]}: {cell(o)} → {cell(arows[pos][c])}" for c, o in ch.items()) \
                    or "the new values equal the old ones, so nothing actually changes"
            else:
                what = "it matched, so MySQL removes it"
            what = f"table row #{pos + 1}: {what}"
            more = len(positions) - MAX_ROW_STEPS
            extra = f" ({plural(more, 'more row')} get the same treatment.)" if k == MAX_ROW_STEPS - 1 and more > 0 else ""
            self.add(i, f"Row {k + 1} of {len(positions)}", f"{what[0].upper() + what[1:]}.{extra}", kind="row",
                     scope=scope, tables=[view(table, cols, rows, list(marks), dict(olds))])

    # --- SELECT, clause by clause in logical order ---

    def query(self, node, ctes, scope, stmt, raw=None):
        if isinstance(node, exp.Subquery):
            node = node.this
        scope_ctes = list(ctes)
        own = node.args.get("with_")
        for cte in own.expressions if own else []:
            if own.args.get("recursive"):
                self.show(with_sql(scope_ctes + [cte]) + f"SELECT * FROM `{cte.alias}`", stmt, f"CTE {cte.alias}",
                          f"WITH RECURSIVE {cte.alias}",
                          lambda n, p, a=cte.alias: f"The recursive CTE {a} starts with its first SELECT, then keeps "
                                                 f"re-running the part after UNION on the newest rows until no new rows "
                                                 f"appear. It ended with {plural(n, 'row')}.")
            else:
                self.query(cte.this, scope_ctes, f"CTE {cte.alias}", stmt)
            scope_ctes.append(cte)
        pre = with_sql(scope_ctes)
        base = node.copy()
        base.set("with_", None)
        sub = lambda s: f"{scope} › {s}" if scope else s
        done = lambda n: (f" This is the final result: {plural(n, 'row')}." if raw else
                          f" This is the result of {scope}: {plural(n, 'row')}." if scope else "")
        final_sql = raw or pre + base.sql("mysql")

        if isinstance(base, exp.SetOperation):
            self.query(node.this, scope_ctes, sub("left side"), stmt)
            self.query(node.expression, scope_ctes, sub("right side"), stmt)
            op = base.key.upper()
            dedupe = base.args.get("distinct")
            why = {"UNION": "stacks both results on top of each other",
                   "INTERSECT": "keeps only rows that appear in both results",
                   "EXCEPT": "keeps rows from the left side that are not in the right side"}.get(op, "combines both results")
            self.show(final_sql, stmt, scope, f"{op}{'' if dedupe else ' ALL'}",
                      lambda n, p: f"{op} {why}{', then removes duplicate rows' if dedupe else ' (ALL keeps duplicates)'}."
                                + done(n), final=True)
            return
        if not isinstance(base, exp.Select):
            self.show(final_sql, stmt, scope, "Run query", lambda n, p: "Ran the query." + done(n), final=True)
            return

        frm = base.args.get("from_")
        joins = base.args.get("joins") or []
        where, group, having = (base.args.get(k) for k in ("where", "group", "having"))
        later = [k for k in ("distinct", "order", "limit") if base.args.get(k)]
        if not frm:  # SELECT (subquery) AS x: step through each subquery, then its answer becomes the value
            vals = []
            for e in base.expressions:
                name = e.alias_or_name or e.sql("mysql")
                self.subqueries(e, base, pre, scope_ctes, sub(f"subquery for {name}"), stmt)
                vals.append({"name": name, "sql": e.unalias().sql("mysql"), "sub": isinstance(e.unalias(), exp.Subquery)})
            self.show(final_sql, stmt, scope, "SELECT " + ", ".join(v["name"] for v in vals),
                      lambda n, p: "No FROM, so SELECT just computes the values. A subquery used as a value gives its one "
                                   "answer, or NULL when it finds no rows." + done(n),
                      final=True, detail={"type": "values", "cols": vals})
            return

        sources = [frm.this] + [j.this for j in joins]
        for s in sources:
            if isinstance(s, exp.Subquery):
                self.query(s.this, scope_ctes, sub(f"derived table {s.alias}"), stmt)
        names = [s.alias_or_name for s in sources]
        src_cols = [self.run(f"{pre}SELECT * FROM {s.sql('mysql')} LIMIT 0")[0] for s in sources]
        multi = len(sources) > 1
        labels = [f"{a}.{c}" if multi else c for a, cs in zip(names, src_cols) for c in cs]
        star = ", ".join(f"`{a}`.*" for a in names)
        count = [0]  # rows flowing out of the previous step

        def step(sql, title, explain, **kw):
            n = self.show(sql, stmt, scope, title, explain, prev=count[0], **kw)
            if n is not None:
                count[0] = n
            return n

        first = sources[0]
        what = f"the result of derived table {first.alias}" if isinstance(first, exp.Subquery) else \
            f"CTE {first.name}" if first.name in {c.alias for c in scope_ctes} else f"table {first.name}"
        step(f"{pre}SELECT * FROM {first.sql('mysql')}", frm.sql("mysql"),
             lambda n, p: f"FROM runs first: start with every row of {what} ({plural(n, 'row')})." + (
                 f" This is its own separate read of {first.name}: whatever this part does only shapes its own "
                 f"result, and the outer query's rows are not touched." if scope and isinstance(first, exp.Table) else ""),
             labels=labels[:len(src_cols[0])])

        body = f"FROM {first.sql('mysql')}"
        for k, j in enumerate(joins, 1):
            body += (" " if not j.sql("mysql").startswith(",") else "") + j.sql("mysql")
            side, on = j.side, j.args.get("on") or j.args.get("using")
            tname = names[k]
            if not on:
                desc = (f"pairs every row so far with every row of {tname} (a cross join). "
                        + ("WHERE usually filters these pairs down next." if where else ""))
            elif side:
                desc = (f"pairs rows with matching rows of {tname}. As a {side} JOIN, rows from the "
                        f"{side.lower()} side with no match are kept anyway, with NULLs filled in.")
            else:
                desc = f"pairs rows with rows of {tname} where the ON condition is true. Rows with no match are dropped."
            src = sources[k]
            if isinstance(src, exp.Table) and src.name.lower() in [x.name.lower() for x in sources[:k] if isinstance(x, exp.Table)]:
                desc += f" ({src.name} is the same stored table read a second time, under the name {tname}.)"
            det, pcols = checks(on, self.text) if isinstance(on, exp.Expression) else ({"checks": []}, [])
            self.fill_lists(det, pre)
            step(f"{pre}SELECT {', '.join(f'`{a}`.*' for a in names[:k + 1])}{''.join(', ' + c for c in pcols)} {body}",
                 j.sql("mysql").lstrip(", "),
                 lambda n, p, d=desc, on=on: f"{'JOIN' if on else 'Comma join'} {d} {p} rows → {plural(n, 'row')}.",
                 labels=labels[:sum(len(c) for c in src_cols[:k + 1])], extra=len(pcols),
                 detail={"type": "join", "left": sum(len(c) for c in src_cols[:k]), "side": side, "table": tname,
                         # the right table on its own, so the page can show both sides before they merge
                         "right": [[cell(x) for x in r] for r in self.run(f"{pre}SELECT * FROM {src.sql('mysql')}")[1][:MAX_ROWS]],
                         **det})

        if where:
            self.subqueries(where, base, pre, scope_ctes, sub("subquery in WHERE"), stmt)
            det, pcols = checks(where.this, self.text)
            self.fill_lists(det, pre)
            step(f"{pre}SELECT {star}, ({where.this.sql('mysql')}) IS TRUE AS `__keep`, {', '.join(pcols)} {body}",
                 where.sql("mysql"),
                 lambda n, p: f"WHERE checks each row and keeps only rows where the condition is true "
                              f"(NULL counts as not true). Kept {plural(n, 'row')} of {p}; the crossed-out rows are dropped.",
                 labels=labels, keep=True, extra=len(pcols), detail={"type": "filter", **det})
            body += f" WHERE {where.this.sql('mysql')}"

        alias_map = {e.alias: e.this for e in base.expressions if isinstance(e, exp.Alias)}
        all_cols = {c for cs in src_cols for c in cs}

        def resolve(e):  # GROUP BY 1 / GROUP BY alias → the real expression
            if isinstance(e, exp.Literal) and e.is_int:
                return base.expressions[int(e.this) - 1].unalias().copy()
            return e.copy().transform(lambda x: alias_map[x.name].copy() if isinstance(x, exp.Column) and not x.table
                                      and x.name in alias_map and x.name not in all_cols else x)

        keys = [resolve(k).sql("mysql") for k in group.expressions] if group else []
        if group:
            ks = ", ".join(keys)
            order = base.args.get("order")
            found = top_aggs(base.expressions + ([resolve(having.this)] if having else []) + (order.expressions if order else []))
            aggs, argcols = list(found), []

            def ref(sql):
                argcols.append(f"({sql})")
                return len(argcols) - 1
            ainfo = [agg_info(a, ref, self.text) for a in found.values()]
            step(f"{pre}SELECT {star}, DENSE_RANK() OVER (ORDER BY {ks}) AS `__grp`{''.join(', ' + c for c in argcols)} {body} ORDER BY {ks}",
                 group.sql("mysql"),
                 lambda n, p: f"GROUP BY gathers rows with the same {ks} into one group. Each color band below is one "
                              f"group. From here on, each group becomes a single row, so only the grouped columns "
                              f"and aggregates like COUNT() or SUM() can be shown.",
                 labels=labels, grouped=True, extra=len(argcols), detail={})
            # each group collapses to one whole row: the other columns hold the value MySQL picks from the group
            norm = lambda x: x.replace("`", "").lower()
            refs = [f"`{a}`.`{c}`" for a, cs in zip(names, src_cols) for c in cs]
            other = [(lab, ref) for lab, ref in zip(labels, refs) if not {norm(lab), norm(ref)} & {norm(k) for k in keys}]
            try:
                cols, rows = self.run(f"{pre}SELECT {', '.join(keys + [f'ANY_VALUE({r})' for _, r in other] + aggs)} "
                                      f"{body} GROUP BY {ks} ORDER BY {ks}")
                self.steps[-1]["detail"] = {
                    **(self.steps[-1].get("detail") or {}), "aggs": ainfo,  # rows: what each aggregate reads per row
                    "type": "group", "keys": keys, "picked": len(other),
                    "summary": view("After GROUP BY", keys + [lab for lab, _ in other] + aggs, rows),
                    "aliases": {e.this.sql("mysql"): e.alias for e in base.expressions if isinstance(e, exp.Alias)}}
            except pymysql.MySQLError:
                pass
        if having:
            self.subqueries(having, base, pre, scope_ctes, sub("subquery in HAVING"), stmt)
            h = resolve(having.this)
            aggs = list(dict.fromkeys(a.sql("mysql") for a in h.find_all(exp.AggFunc)))
            cols = ", ".join(keys + aggs)
            det, pcols = checks(h, self.text)
            self.fill_lists(det, pre)
            step(f"{pre}SELECT {cols + ', ' if cols else ''}({h.sql('mysql')}) IS TRUE AS `__keep`, {', '.join(pcols)} {body}"
                 + (f" GROUP BY {', '.join(keys)}" if keys else ""), having.sql("mysql"),
                 lambda n, p: f"HAVING filters whole groups (WHERE filters single rows, before grouping). "
                              f"Kept {plural(n, 'group')}; the crossed-out groups are dropped.", keep=True,
                 extra=len(pcols), detail={"type": "filter", "groups": True, **det})

        self.subqueries(base.expressions, base, pre, scope_ctes, sub("subquery in SELECT"), stmt)
        q = base.copy()
        for k in ("distinct", "order", "limit", "offset"):
            q.set(k, None)
        notes = []
        if any(e.find(exp.Window) for e in base.expressions):
            notes.append("Window functions (… OVER (…)) are calculated now, after WHERE, GROUP BY and HAVING, "
                         "without merging rows.")
        if not group and any(a.find_ancestor(exp.Window, exp.Subquery) is None
                             for e in base.expressions for a in e.find_all(exp.AggFunc)):
            notes.append("There is an aggregate but no GROUP BY, so all rows are treated as one group.")
        if any(e.find(exp.Case) for e in base.expressions):
            notes.append("CASE is checked top to bottom for each row, and the first WHEN that is true wins.")
        cols_txt = ", ".join(e.alias if isinstance(e, exp.Alias) else e.sql("mysql") for e in base.expressions)
        n = step(final_sql if not later else pre + q.sql("mysql"), "SELECT " + cols_txt,
                 lambda n, p: f"SELECT now builds the output columns ({cols_txt}). " + " ".join(notes) +
                              (done(n) if not later else ""), final=not later)
        if n is not None:
            self.select_detail(base, q, pre)

        if base.args.get("distinct"):
            q.set("distinct", base.args["distinct"].copy())
            last = later[-1] == "distinct"
            step(final_sql if last else pre + q.sql("mysql"), "DISTINCT",
                 lambda n, p: f"DISTINCT removes duplicate rows: {p} → {plural(n, 'row')}." + (done(n) if last else ""),
                 final=last)
        if base.args.get("order"):
            q.set("order", base.args["order"].copy())
            last = later[-1] == "order"
            step(final_sql if last else pre + q.sql("mysql"), base.args["order"].sql("mysql"),
                 lambda n, p: "ORDER BY sorts the rows (ascending unless DESC; in MySQL, NULLs sort first when "
                              "ascending)." + (done(n) if last else ""), final=last)
        if base.args.get("limit"):
            off = base.args.get("offset")
            step(final_sql, (base.args["limit"].sql("mysql") + (" " + off.sql("mysql") if off else "")),
                 lambda n, p: f"LIMIT keeps only {plural(n, 'row')}" + (" after skipping the first ones" if off else "")
                              + f" out of {p}." + done(n), final=True)

    def fill_lists(self, det, pre):
        """For `x IN (subquery)` checks, show the list the subquery produced."""
        for c in det["checks"]:
            if "query" in c:
                try:
                    c["list"] = [cell(r[0]) for r in self.run(pre + c.pop("query"))[1][:30]]
                except pymysql.MySQLError:
                    pass  # correlated: the list depends on the outer row

    def select_detail(self, base, q, pre):
        """Per output column: its expression, and per row how its value came out: for CASE which WHEN hit,
        for a calculation each step's value, for a window function the rows it read."""
        cols, extra, seen = [], [], {}

        def ref(sql):  # the extra column holding this value for each row
            if sql not in seen:
                seen[sql] = len(extra)
                extra.append(f"({sql})")
            return seen[sql]
        for e in base.expressions:
            inner = e.unalias()
            d = {"name": e.alias_or_name or e.sql("mysql"), "sql": inner.sql("mysql"), "alias": isinstance(e, exp.Alias), "star": isinstance(inner, exp.Star),
                 "window": bool(inner.find(exp.Window)),
                 "agg": any(not a.find_ancestor(exp.Window, exp.Subquery) for a in inner.find_all(exp.AggFunc))}
            if isinstance(inner, (exp.Case, exp.If)):
                # IF(c, a, IF(c2, b, d)) reads like CASE WHEN c THEN a WHEN c2 THEN b ELSE d
                ifs, tail = [], inner
                while isinstance(tail, exp.If):
                    ifs.append(exp.If(this=tail.this.copy(), true=tail.args["true"].copy()))
                    tail = tail.args.get("false")
                if isinstance(inner, exp.Case):
                    ifs, tail = inner.args.get("ifs") or [], inner.args.get("default")
                d["case"] = {"else": tail.sql("mysql") if tail else "NULL", "if": isinstance(inner, exp.If),
                             "operand": inner.this.sql("mysql") if isinstance(inner, exp.Case) and inner.this else None,
                             "branches": []}
                for iff in ifs:
                    cond = exp.EQ(this=inner.this.copy(), expression=iff.this.copy()) if d["case"]["operand"] else iff.this
                    det, pcols = checks(cond, self.text)
                    self.fill_lists(det, pre)
                    # per branch: its overall result (1, 0 or NULL), then its checks' columns
                    d["case"]["branches"].append({"when": iff.this.sql("mysql"), "then": iff.args["true"].sql("mysql"),
                                                  "offset": len(extra), **det})
                    extra += [f"({cond.sql('mysql')})", *pcols]
            else:
                windows = [w for w in inner.find_all(exp.Window) if not w.find_ancestor(exp.Subquery)]
                if windows:
                    d["windows"] = [window_detail(w, ref, w.meta.get("shown"), self.text) for w in windows]
                steps = calc_steps(inner, self.text, ref)
                if steps:
                    d["calc"] = steps
            cols.append(d)
        detail = {"type": "select", "cols": cols}
        found = {} if base.args.get("group") else top_aggs(base.expressions)
        if found:  # no GROUP BY: all rows form one group
            args = []
            detail["aggs"] = [agg_info(a, lambda sql: args.append(sql) or len(args) - 1, self.text) for a in found.values()]
            try:
                for sqls, key in ((args, "agg_rows"), (list(found), "agg_values")):
                    if sqls:
                        q3 = q.copy()
                        q3.set("expressions", [sqlglot.parse_one(x, read="mysql") for x in sqls])
                        detail[key] = [[cell(x) for x in r] for r in self.run(pre + q3.sql("mysql"))[1][:MAX_ROWS]]
            except (pymysql.MySQLError, sqlglot.errors.SqlglotError):
                pass
        if extra:  # run once more with the extra values, then line those rows up with the shown rows by value
            q2 = q.copy()
            for x in extra:
                q2.append("expressions", sqlglot.parse_one(x, read="mysql"))
            try:
                _, rows = self.run(pre + q2.sql("mysql"))
                shown = [tuple(r["v"]) for r in self.steps[-1]["tables"][0]["rows"]]
                pool = [(tuple(cell(x) for x in r[:-len(extra)]), [cell(x) for x in r[-len(extra):]]) for r in rows]
                detail["extra_rows"] = []
                for v in shown:
                    k = next((k for k, (pv, _) in enumerate(pool) if pv == v), None)
                    detail["extra_rows"].append(pool.pop(k)[1] if k is not None else None)
            except pymysql.MySQLError:
                pass
        self.steps[-1]["detail"] = detail

    def subqueries(self, exprs, owner, pre, ctes, scope, stmt):
        """Step into subqueries directly inside this SELECT's clause (one expression or a list)."""
        for s in [s for e in (exprs if isinstance(exprs, list) else [exprs]) for s in e.find_all(exp.Subquery, exp.Exists)]:
            q = s.this
            if not isinstance(q, exp.Query) or owner_query(s) is not owner:
                continue
            try:
                self.run(pre + q.sql("mysql"))
            except pymysql.MySQLError as e:
                if e.args[0] != 1054:  # 1054 = unknown column → it refers to the outer query
                    continue
                self.add(stmt, "Correlated subquery", "This subquery uses columns from the outer query, so MySQL "
                         "runs it again for every outer row instead of once. Its answer for each row feeds into "
                         "the next step.", scope=scope, sql=q.sql("mysql", pretty=True))
                continue
            self.query(q, ctes, scope, stmt)

    def show(self, sql, stmt, scope, title, explain, prev=None, labels=None, keep=False, grouped=False, final=False,
             extra=0, detail=None):
        """Run one stage's SQL and add it as a step. Returns its row count.
        The last `extra` columns are per-row detail values; they go into detail["rows"]."""
        try:
            cols, rows = self.run(sql)
        except pymysql.MySQLError as e:
            if final and not scope:
                raise
            self.add(stmt, title, f"Couldn't preview this stage (MySQL said: {e.args[-1]}).", kind="note", scope=scope)
            return None
        marks = groups = None
        if extra:
            detail["rows"] = [[cell(x) for x in r[-extra:]] for r in rows[:MAX_ROWS]]
            cols, rows = cols[:-extra], [r[:-extra] for r in rows]
        if keep:
            marks = [None if r[-1] else "dropped" for r in rows]
            cols, rows = cols[:-1], [r[:-1] for r in rows]
        if grouped:
            groups = [r[-1] for r in rows]
            cols, rows = cols[:-1], [r[:-1] for r in rows]
        if labels and len(labels) == len(cols):
            cols = labels
        n = sum(1 for m in marks if not m) if marks else len(rows)
        text = explain(n, prev)
        name = ("Final result" if final and not scope else f"Result of {scope}" if final else "Rows at this stage")
        self.add(stmt, title, text, kind="result" if final else "query", scope=scope,
                 tables=[view(name, cols, rows, marks, groups=groups)])
        if detail:
            self.steps[-1]["detail"] = detail
        return n


def run_all(setup, code):
    stmts = [{"text": s, "phase": "setup"} for s in split_sql(setup)] + \
            [{"text": s, "phase": "code"} for s in split_sql(code)]
    if len(stmts) > MAX_STATEMENTS:
        return {"error": f"That's {len(stmts)} statements. The limit is {MAX_STATEMENTS}."}
    # Each run gets its own database and a user that can only touch that database, since anyone's
    # SQL runs here. root (admin) sets them up, stops a run that goes too long, and cleans up.
    name, pw = "step_" + uuid.uuid4().hex[:12], secrets.token_hex(16)
    admin = connect()
    acur = admin.cursor()
    acur.execute(f"CREATE DATABASE `{name}`")
    acur.execute(f"CREATE USER '{name}'@'%' IDENTIFIED BY '{pw}' WITH MAX_USER_CONNECTIONS 1")
    acur.execute(f"GRANT ALL ON `{name}`.* TO '{name}'@'%'")
    conn = connect(name, pw, name)
    cur = conn.cursor()
    cur.execute("SET SESSION max_execution_time = 5000")  # stop runaway SELECTs after 5s
    # the whole run (UPDATE loops, SLEEP, ...) is cut off after RUN_SECONDS
    killed = threading.Event()
    def kill():
        killed.set()
        with connect() as c, c.cursor() as k:
            k.execute(f"KILL {conn.thread_id()}")
    watchdog = threading.Timer(RUN_SECONDS, kill)
    watchdog.start()
    def err(e):
        return (f"Stopped: your code ran longer than {RUN_SECONDS} seconds." if killed.is_set()
                else f"MySQL error {e.args[0]}: {e.args[-1]}")
    st = Stepper(cur)
    try:
        for i, s in enumerate(stmts):
            if s["phase"] == "setup":
                try:
                    cur.execute(s["text"])
                    cur.fetchall()
                except pymysql.MySQLError as e:
                    st.add(i, "Error in schema", err(e), kind="error")
                    return {"statements": stmts, "steps": st.steps}
        st.add(None, "Starting tables", "Your schema ran. These are the tables before your code starts.",
               kind="start", tables=[view(n, c, r) for n, (c, r) in st.snapshot().items()])
        for i, s in enumerate(stmts):
            if s["phase"] != "code":
                continue
            try:
                st.statement(s["text"], i)
            except pymysql.MySQLError as e:
                st.add(i, "Error", err(e), kind="error")
                break
        called = " ".join(s["text"] for s in stmts if s["phase"] == "code" and not PROGRAM.match(s["text"]))
        for f in st.funcs.values():
            if not re.search(rf"\b{f['name']}\s*\(", called, re.I) and not any(x["kind"] == "error" for x in st.steps):
                try:
                    st.replay(f, ["1"] * len(f["params"]), auto=True)
                except pymysql.MySQLError as e:
                    st.add(f["stmt"], "Error", err(e), kind="error")
        if not any(s["phase"] == "code" for s in stmts):
            st.steps[-1]["explain"] += " Add some code in the second box to step through it."
    finally:
        watchdog.cancel()
        if conn.open:
            conn.close()
        acur.execute(f"DROP USER IF EXISTS '{name}'@'%'")
        acur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        admin.close()
    return {"statements": stmts, "steps": st.steps}


# ---------- Web server ----------

RECENT = {}  # visitor -> times of their recent runs
RECENT_LOCK = threading.Lock()


def too_many(who):
    now = time.monotonic()
    with RECENT_LOCK:
        if len(RECENT) > 10_000:  # forget visitors not seen in the last minute
            for k in [k for k, v in RECENT.items() if now - v[-1] > 60]:
                del RECENT[k]
        times = [t for t in RECENT.get(who, []) if now - t < 60] + [now]
        RECENT[who] = times
        return len(times) > RUNS_PER_MINUTE


CHAT_RULES = """You are the helper inside SQL Stepper, a website that steps through MySQL 8.0 code like a \
debugger: clause by clause in the order MySQL runs it (FROM, JOIN, WHERE, GROUP BY, HAVING, SELECT, \
DISTINCT, ORDER BY, LIMIT), showing the table at each step. Users are mostly students practicing \
LeetCode-style SQL problems. You get their schema, their code, and the step they are looking at.
Answer their question about it. Be short, plain, and friendly; use the actual table and column names \
and values. Put SQL in ```sql blocks. If their code has a bug, say exactly what and show the fix. \
The server runs MySQL 8.0 without ONLY_FULL_GROUP_BY, like LeetCode, so selecting a column that isn't \
grouped or aggregated is allowed (MySQL picks a value from the group). Only help with SQL and databases."""


def chat_prompt(data):
    """The conversation for the AI: the rules, then what's on the user's screen, then the chat."""
    c = data.get("context") or {}
    # size caps keep the worst question to about 25k tokens in, so under half a cent
    screen = f"Schema:\n```sql\n{str(c.get('setup', ''))[:12000]}\n```\nCode:\n```sql\n{str(c.get('code', ''))[:8000]}\n```"
    if str(c.get("instructions", "")).strip():
        screen = f"The problem they're solving:\n{str(c['instructions'])[:6000]}\n\n" + screen
    if c.get("step"):
        screen += f"\nThey are looking at this step: {str(c['step'])[:6000]}"
    msgs = [{"role": "system", "content": CHAT_RULES + "\n\n" + screen}]
    for m in (data.get("messages") or [])[-10:]:
        if m.get("role") in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": str(m.get("content", ""))[:6000]})
    return msgs


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/config":
            return self.reply({"ai": bool(AI_KEY), "ai_note": AI_NOTE})
        self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path not in ("/run", "/chat"):
            return self.send(404, b"", "text/plain")
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            return self.reply({"error": "That's too much for one request (the limit is about 200 KB)."})
        who = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip() if TRUST_PROXY else "") or self.client_address[0]
        if self.path == "/chat":
            return self.chat(json.loads(self.rfile.read(size)))
        if too_many(who):
            return self.reply({"error": "Too many runs in the last minute. Wait a bit and try again."})
        if not SLOTS.acquire(timeout=RUN_SECONDS + 5):
            return self.reply({"error": "The site is busy right now. Try again in a few seconds."})
        try:
            data = json.loads(self.rfile.read(size))
            result = run_all(str(data.get("setup", "")), str(data.get("code", "")))
        except Exception as e:  # show anything unexpected in the page instead of hanging
            result = {"error": f"{type(e).__name__}: {e}"}
        finally:
            SLOTS.release()
        self.reply(result)

    def chat(self, data):
        """Streams the AI's answer back as plain text while it's being written."""
        if not AI_KEY:
            return self.send(503, b"The AI chat isn't set up on this server.", "text/plain; charset=utf-8")
        if PROXY_SECRET and not secrets.compare_digest(self.headers.get("X-Proxy-Secret", ""), PROXY_SECRET):
            return self.send(403, b"Use the chat at sqlstepper.psbhr.com.", "text/plain; charset=utf-8")
        req = urllib.request.Request(AI_URL, json.dumps({"model": AI_MODEL, "messages": chat_prompt(data), "stream": True, "max_tokens": 2000,
                                                          # little hidden "thinking": a long think used up the whole
                                                          # answer allowance and left the reply empty
                                                          "reasoning": {"effort": "low", "exclude": True},
                                                          "provider": {"only": AI_HOSTS, "zdr": True, "data_collection": "deny"}}).encode(),
                                     {"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json",
                                      "HTTP-Referer": "https://sqlstepper.psbhr.com", "X-Title": "SQL Stepper"})
        try:
            upstream = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            why = e.read()[:300]
            if e.code in (402, 403) and re.search(rb"limit|credit", why, re.I):  # the daily $ cap
                print("AI_BUDGET_REACHED", e.code, why, flush=True)
                return self.send(502, b"The AI helper has reached today's limit. It will be back tomorrow.", "text/plain; charset=utf-8")
            print("chat error", e.code, why, flush=True)
            msg = "The AI is busy right now. Try again in a minute." if e.code == 429 else "The AI couldn't answer right now. Try again in a bit."
            return self.send(502, msg.encode(), "text/plain; charset=utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with upstream:
            for line in upstream:  # server-sent events: "data: {...}" per piece of text
                if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                    continue
                try:
                    piece = json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if piece:
                    self.wfile.write(piece.encode())
                    self.wfile.flush()

    def reply(self, result):
        self.send(200, json.dumps(result).encode(), "application/json")

    def log_message(self, *args):
        pass


def main():
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Already running at {url}")
        webbrowser.open(url)
        return
    start_mysql()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"SQL Stepper running at {url}  (Ctrl+C to stop)", flush=True)
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
