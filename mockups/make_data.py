# Rebuild mockups/data.js from the real backend: .venv/bin/python mockups/make_data.py
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import run_all, start_mysql  # noqa: E402

TREE_SETUP = """Create table If Not Exists Tree (id int, p_id int)
Truncate table Tree
insert into Tree (id, p_id) values ('1', NULL)
insert into Tree (id, p_id) values ('2', '1')
insert into Tree (id, p_id) values ('3', '1')
insert into Tree (id, p_id) values ('4', '2')
insert into Tree (id, p_id) values ('5', '2')"""
TREE_CODE = """SELECT id,
  CASE
    WHEN p_id IS NULL THEN 'Root'
    WHEN id IN (SELECT p_id FROM Tree) THEN 'Inner'
    ELSE 'Leaf'
  END AS type
FROM Tree
ORDER BY id;"""
EMP_SETUP = """CREATE TABLE Employee (id int primary key, name varchar(20), salary int, dept varchar(5), managerId int);
INSERT INTO Employee VALUES (1,'Joe',70000,'A',3),(2,'Henry',80000,'B',4),(3,'Sam',60000,'A',NULL),(4,'Max',90000,'B',NULL),(5,'Amy',80000,'A',3);"""
EMP_CODE = """UPDATE Employee SET salary = salary * 1.1 WHERE dept = 'A';

SELECT dept, COUNT(*) AS n, AVG(salary) AS avg_pay
FROM Employee
WHERE salary > 60000
GROUP BY dept
HAVING n >= 2
ORDER BY avg_pay DESC;"""
JOIN_CODE = """SELECT e.name AS employee, m.name AS manager
FROM Employee e
LEFT JOIN Employee m ON e.managerId = m.id
WHERE e.salary > 65000
ORDER BY e.name;"""

start_mysql()
out = [
    {"name": name, "setup": setup, "code": code, **run_all(setup, code)}
    for name, setup, code in [
        ("Tree node types (CASE + subquery)", TREE_SETUP, TREE_CODE),
        ("Raise, then department report (UPDATE + GROUP BY)", EMP_SETUP, EMP_CODE),
        ("Employees and managers (LEFT JOIN)", EMP_SETUP, JOIN_CODE),
    ]
]
Path(__file__).with_name("data.js").write_text(
    "// Real step data from app.py run_all(). Rebuild with mockups/make_data.py\nwindow.SCENARIOS = "
    + json.dumps(out, indent=1)
    + ";\n"
)
print("wrote", [len(s["steps"]) for s in out], "steps")
