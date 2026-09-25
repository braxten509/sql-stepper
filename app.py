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
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pymysql
import sqlglot
from sqlglot import exp

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sql-stepper"
BASE, DATA, SOCK = HOME / "mysql", HOME / "data", HOME / "mysql.sock"
MYSQL_URL = "https://cdn.mysql.com/Downloads/MySQL-8.0/mysql-8.0.46-linux-glibc2.17-x86_64-minimal.tar.xz"
PORT = int(os.environ.get("PORT", 8765))
MAX_ROWS = 300  # ponytail: display cap per table, raise if you step through big tables
MAX_ROW_STEPS = 12  # per-row steps shown for one UPDATE/DELETE


# ---------- MySQL server ----------

# MySQL 8's default sql_mode minus ONLY_FULL_GROUP_BY, which LeetCode also runs without
# (so "SELECT a, b ... GROUP BY a" works there and here).
SQL_MODE = "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"


def connect():
    return pymysql.connect(unix_socket=str(SOCK), user="root", autocommit=True, connect_timeout=2,
                           init_command=f"SET SESSION sql_mode = '{SQL_MODE}'")


def start_mysql():
    try:
        connect().close()  # already running (left over from a previous session)
        return
    except pymysql.err.OperationalError:
        pass
    if not BASE.exists():
        print("Downloading MySQL 8.0 (one time, about 60 MB)...", flush=True)
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = HOME / "mysql.tar.xz"
        urllib.request.urlretrieve(MYSQL_URL, tmp)
        with tarfile.open(tmp) as t:
            t.extractall(HOME, filter="data")
        tmp.unlink()
        next(HOME.glob("mysql-8.0.*")).rename(BASE)
    mysqld = str(BASE / "bin/mysqld")
    common = ["--no-defaults", f"--basedir={BASE}", f"--datadir={DATA}"]
    if not DATA.exists():
        print("Setting up MySQL data folder (one time)...", flush=True)
        subprocess.run([mysqld, *common, "--initialize-insecure"], check=True, capture_output=True)
    proc = subprocess.Popen([mysqld, *common, f"--socket={SOCK}", "--skip-networking", "--mysqlx=OFF",
                             f"--pid-file={HOME / 'mysqld.pid'}", f"--log-error={HOME / 'mysqld.log'}"])
    atexit.register(proc.terminate)
    for _ in range(160):
        if proc.poll() is not None:
            break
        try:
            connect().close()
            return
        except pymysql.err.OperationalError:
            time.sleep(0.25)
    sys.exit(f"MySQL failed to start. See {HOME / 'mysqld.log'}")


# ---------- Splitting pasted SQL into statements ----------

STMT_START = re.compile(r"\s*(select|with|insert|update|delete|create|drop|alter|truncate|replace)\b", re.I)


def split_semicolons(text):
    """Split on ; outside quotes, dropping comments."""
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


COMPARE = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.NullSafeEQ, exp.Is)


def checks(cond):
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
    out, cols = [], []
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
        out.append(d)
    return {"combine": kind.key.upper() if kind else None, "checks": out}, cols


def owner_query(node):
    p = node.parent
    while p is not None and not isinstance(p, exp.Query):
        p = p.parent
    return p


class Stepper:
    def __init__(self, cur):
        self.cur, self.steps = cur, []

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
        try:
            node = sqlglot.parse_one(text, read="mysql")
        except sqlglot.errors.SqlglotError:
            node = None
        if isinstance(node, exp.Query):
            self.run(text)  # real error? fail here, before any previews
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
        t = tbl.name if tbl else "the table"
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

    # --- UPDATE / DELETE, one row at a time ---

    def find_rows(self, node):
        """Before running an UPDATE/DELETE: which rows of the target table will it touch?"""
        this = node.this
        sources = [this] + [j.this for j in this.args.get("joins") or []]
        real = {s.alias_or_name: s.name for s in sources if isinstance(s, exp.Table)}
        if isinstance(node, exp.Update):
            target = node.expressions[0].this.table or this.alias_or_name
        else:
            target = node.args["tables"][0].alias_or_name if node.args.get("tables") else this.alias_or_name
        table = real[target]
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
            det, pcols = checks(where.this)
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
        if not frm:
            self.show(final_sql, stmt, scope, "SELECT", lambda n, p: "No FROM, so SELECT just computes the values." + done(n),
                      final=True)
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
            if isinstance(src, exp.Table) and src.name in [x.name for x in sources[:k] if isinstance(x, exp.Table)]:
                desc += f" ({src.name} is the same stored table read a second time, under the name {tname}.)"
            det, pcols = checks(on) if isinstance(on, exp.Expression) else ({"checks": []}, [])
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
            det, pcols = checks(where.this)
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
            step(f"{pre}SELECT {star}, DENSE_RANK() OVER (ORDER BY {ks}) AS `__grp` {body} ORDER BY {ks}",
                 group.sql("mysql"),
                 lambda n, p: f"GROUP BY gathers rows with the same {ks} into one group. Each color band below is one "
                              f"group. From here on, each group becomes a single row, so only the grouped columns "
                              f"and aggregates like COUNT() or SUM() can be shown.",
                 labels=labels, grouped=True)
            order = base.args.get("order")
            aggs = list(dict.fromkeys(a.sql("mysql") for e in base.expressions + ([resolve(having.this)] if having else [])
                                      + (order.expressions if order else [])
                                      for a in e.find_all(exp.AggFunc) if not a.find_ancestor(exp.Window, exp.Subquery)))
            # each group collapses to one whole row: the other columns hold the value MySQL picks from the group
            norm = lambda x: x.replace("`", "").lower()
            refs = [f"`{a}`.`{c}`" for a, cs in zip(names, src_cols) for c in cs]
            other = [(lab, ref) for lab, ref in zip(labels, refs) if not {norm(lab), norm(ref)} & {norm(k) for k in keys}]
            try:
                cols, rows = self.run(f"{pre}SELECT {', '.join(keys + [f'ANY_VALUE({r})' for _, r in other] + aggs)} "
                                      f"{body} GROUP BY {ks} ORDER BY {ks}")
                self.steps[-1]["detail"] = {
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
            det, pcols = checks(h)
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
        cols_txt = ", ".join(e.alias_or_name or e.sql("mysql") for e in base.expressions)
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
        """Per output column: its expression, and for CASE which WHEN each row hit."""
        cols, extra = [], []
        for e in base.expressions:
            inner = e.unalias()
            d = {"name": e.alias_or_name or e.sql("mysql"), "sql": inner.sql("mysql"), "star": isinstance(inner, exp.Star),
                 "window": bool(inner.find(exp.Window)),
                 "agg": any(not a.find_ancestor(exp.Window, exp.Subquery) for a in inner.find_all(exp.AggFunc))}
            if isinstance(inner, exp.Case):
                d["case"] = {"else": inner.args["default"].sql("mysql") if inner.args.get("default") else "NULL",
                             "operand": inner.this.sql("mysql") if inner.this else None, "branches": []}
                for iff in inner.args.get("ifs") or []:
                    cond = exp.EQ(this=inner.this.copy(), expression=iff.this.copy()) if inner.this else iff.this
                    det, pcols = checks(cond)
                    self.fill_lists(det, pre)
                    # per branch: its overall result (1, 0 or NULL), then its checks' columns
                    d["case"]["branches"].append({"when": iff.this.sql("mysql"), "then": iff.args["true"].sql("mysql"),
                                                  "offset": len(extra), **det})
                    extra += [f"({cond.sql('mysql')})", *pcols]
            cols.append(d)
        detail = {"type": "select", "cols": cols}
        if extra:  # run once more with the WHEN checks, then line those rows up with the shown rows by value
            q2 = q.copy()
            for x in extra:
                q2.append("expressions", sqlglot.parse_one(x, read="mysql"))
            try:
                _, rows = self.run(pre + q2.sql("mysql"))
                shown = [tuple(r["v"]) for r in self.steps[-1]["tables"][0]["rows"]]
                pool = [(tuple(cell(x) for x in r[:-len(extra)]), [cell(x) for x in r[-len(extra):]]) for r in rows]
                detail["case_rows"] = []
                for v in shown:
                    k = next((k for k, (pv, _) in enumerate(pool) if pv == v), None)
                    detail["case_rows"].append(pool.pop(k)[1] if k is not None else None)
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
    db = "step_" + uuid.uuid4().hex[:12]
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE `{db}`")
    cur.execute(f"USE `{db}`")
    cur.execute("SET SESSION max_execution_time = 5000")  # stop runaway SELECTs after 5s
    st = Stepper(cur)
    stmts = [{"text": s, "phase": "setup"} for s in split_sql(setup)] + \
            [{"text": s, "phase": "code"} for s in split_sql(code)]
    try:
        for i, s in enumerate(stmts):
            if s["phase"] == "setup":
                try:
                    cur.execute(s["text"])
                    cur.fetchall()
                except pymysql.MySQLError as e:
                    st.add(i, "Error in schema", f"MySQL error {e.args[0]}: {e.args[-1]}", kind="error")
                    return {"statements": stmts, "steps": st.steps}
        st.add(None, "Starting tables", "Your schema ran. These are the tables before your code starts.",
               kind="start", tables=[view(n, c, r) for n, (c, r) in st.snapshot().items()])
        for i, s in enumerate(stmts):
            if s["phase"] != "code":
                continue
            try:
                st.statement(s["text"], i)
            except pymysql.MySQLError as e:
                st.add(i, "Error", f"MySQL error {e.args[0]}: {e.args[-1]}", kind="error")
                break
        if not any(s["phase"] == "code" for s in stmts):
            st.steps[-1]["explain"] += " Add some code in the second box to step through it."
    finally:
        cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
        conn.close()
    return {"statements": stmts, "steps": st.steps}


# ---------- Web server ----------

class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path != "/run":
            return self.send(404, b"", "text/plain")
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            result = run_all(data.get("setup", ""), data.get("code", ""))
        except Exception as e:  # show anything unexpected in the page instead of hanging
            result = {"error": f"{type(e).__name__}: {e}"}
        self.send(200, json.dumps(result).encode(), "application/json")

    def log_message(self, *args):
        pass


def main():
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
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
