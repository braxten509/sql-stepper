"""Regression checks against a private, temporary MySQL data directory."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def check():
    from app import run_all, split_sql, start_mysql

    TREE = """Create table If Not Exists Tree (id int, p_id int)
    Truncate table Tree
    insert into Tree (id, p_id) values ('1', NULL)
    insert into Tree (id, p_id) values ('2', '1')
    insert into Tree (id, p_id) values ('3', '1')
    insert into Tree (id, p_id) values ('4', '2')
    insert into Tree (id, p_id) values ('5', '2')"""

    EMP = """CREATE TABLE Employee (id int, name varchar(20), salary int, managerId int, dept varchar(5));
    INSERT INTO Employee VALUES (1,'Joe',70000,3,'A'),(2,'Henry',80000,4,'B'),(3,'Sam',60000,NULL,'A'),(4,'Max',90000,NULL,'B'),(5,'Amy',80000,4,'A');"""

    def titles(r):
        return [(s["scope"], s["title"]) for s in r["steps"]]

    def final(r):
        return [row["v"] for row in r["steps"][-1]["tables"][0]["rows"]]

    assert len(split_sql(TREE)) == 7
    assert split_sql(
        "select a\nfrom t\nwhere x in (\nselect y from u)\nunion\nselect 1;select 2"
    ) == ["select a\nfrom t\nwhere x in (\nselect y from u)\nunion\nselect 1", "select 2"]
    start_mysql()

    # LeetCode 608: CASE + uncorrelated IN subquery
    r = run_all(
        TREE,
        "select id, case when p_id is null then 'Root' when id in (select p_id from Tree) then 'Inner' "
        "else 'Leaf' end as type from Tree order by id",
    )
    t = titles(r)
    assert t[0] == ("", "Starting tables") and len(r["steps"][0]["tables"][0]["rows"]) == 5, t
    assert any(s.startswith("subquery in SELECT") for s, _ in t), t
    assert final(r) == [[1, "Root"], [2, "Inner"], [3, "Leaf"], [4, "Leaf"], [5, "Leaf"]], final(r)

    # WHERE marks dropped rows; GROUP BY bands; HAVING keeps groups
    r = run_all(
        EMP,
        "SELECT dept, COUNT(*) c FROM Employee WHERE salary > 60000 GROUP BY dept HAVING c >= 2",
    )
    w = next(s for s in r["steps"] if s["title"].startswith("WHERE"))
    assert sum(1 for x in w["tables"][0]["rows"] if x.get("m") == "dropped") == 1, w
    g = next(s for s in r["steps"] if s["title"].startswith("GROUP BY"))
    assert {x["g"] for x in g["tables"][0]["rows"]} == {1, 2}, g
    assert sorted(final(r)) == [["A", 2], ["B", 2]], final(r)

    # self join + CTE + window function + correlated subquery
    r = run_all(
        EMP,
        """WITH ranked AS (SELECT e.name, e.salary, m.name AS boss,
                          DENSE_RANK() OVER (ORDER BY e.salary DESC) rk
                        FROM Employee e LEFT JOIN Employee m ON e.managerId = m.id)
                        SELECT name, boss FROM ranked r WHERE rk = 2
                          AND salary >= (SELECT AVG(salary) FROM Employee x WHERE x.dept = 'A' AND x.name <> r.name)""",
    )
    t = titles(r)
    assert any(s == "CTE ranked" and x.startswith("LEFT JOIN") for s, x in t), t
    assert any(x == "Correlated subquery" for _, x in t), t
    assert sorted(final(r)) == [["Amy", "Max"], ["Henry", "Max"]], final(r)

    # LeetCode 196: multi-table DELETE, row by row, then the real change
    r = run_all(
        "CREATE TABLE Person (id int primary key, email varchar(50));"
        "INSERT INTO Person VALUES (1,'john@x.com'),(2,'bob@x.com'),(3,'john@x.com')",
        "DELETE p1 FROM Person p1, Person p2 WHERE p1.email = p2.email AND p1.id > p2.id",
    )
    t = titles(r)
    assert ("DELETE row by row", "Row 1 of 1") in t, t
    last = r["steps"][-1]["tables"][0]
    assert [x["v"] for x in last["rows"] if x.get("m") == "removed"] == [[3, "john@x.com"]], last

    # UPDATE with CASE shows old → new per row
    r = run_all(
        "create table Salary (id int, sex char(1)); insert into Salary values (1,'m'),(2,'f')",
        "UPDATE Salary SET sex = CASE sex WHEN 'm' THEN 'f' ELSE 'm' END",
    )
    assert [x for _, x in titles(r)][1:4] == ["Find rows to update", "Row 1 of 2", "Row 2 of 2"], (
        titles(r)
    )
    assert r["steps"][-1]["tables"][0]["rows"][0] == {
        "v": [1, "f"],
        "m": "changed",
        "old": {1: "m"},
    }, r["steps"][-1]

    # UNION and errors
    r = run_all(
        EMP,
        "SELECT name FROM Employee WHERE dept='A' UNION SELECT name FROM Employee WHERE salary > 85000",
    )
    assert r["steps"][-1]["title"] == "UNION" and len(final(r)) == 4, titles(r)
    r = run_all(EMP, "SELECT nope FROM Employee; SELECT 1")
    assert r["steps"][-1]["kind"] == "error" and "nope" in r["steps"][-1]["explain"], r["steps"][-1]

    # LeetCode-style function: the body's ; don't split it, and it gets called and stepped through
    FN = """CREATE FUNCTION nth(N INT) RETURNS INT
    BEGIN
      set n = n - 1;
      RETURN (select salary from Employee group by salary order by salary desc limit 1 offset n);
    END"""
    r = run_all(EMP, FN)
    assert (
        any(s["title"] == "set n = n - 1" for s in r["steps"])
        and r["steps"][-1]["kind"] == "result"
    ), titles(r)
    r = run_all(EMP, FN + "\nSELECT nth(2)")
    assert (
        any(s["title"].startswith("LIMIT 1 OFFSET 1") for s in r["steps"])
        and r["steps"][-1]["kind"] == "result"
    ), titles(r)

    # SELECT with no FROM: the subquery inside is stepped through before its answer becomes the value
    r = run_all(
        EMP,
        "SELECT (SELECT salary FROM Employee GROUP BY salary ORDER BY salary DESC LIMIT 1 OFFSET 1) AS second",
    )
    assert any(
        s["scope"] == "subquery for second" and s["title"] == "FROM Employee" for s in r["steps"]
    ), titles(r)
    assert r["steps"][-1]["detail"]["type"] == "values", titles(r)
    print("all good")


def main():
    # Reuse only immutable MySQL binaries, never the developer's data or socket.
    cached_mysql = (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sql-stepper/mysql"
    )
    with tempfile.TemporaryDirectory(prefix="sql-stepper-test-") as tmp:
        home = Path(tmp) / "sql-stepper"
        home.mkdir()
        if cached_mysql.is_dir():
            (home / "mysql").symlink_to(cached_mysql.resolve(), target_is_directory=True)
        result = subprocess.run(
            [sys.executable, "-c", "import test_stepper; test_stepper.check()"],
            cwd=Path(__file__).resolve().parent,
            env={**os.environ, "XDG_DATA_HOME": tmp, "NO_BROWSER": "1"},
        )
        # app's atexit handler terminates MySQL; let it finish before removing data.
        deadline = time.monotonic() + 15
        while (home / "mysql.sock").exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("Test MySQL did not shut down within 15 seconds")
            time.sleep(0.1)
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
