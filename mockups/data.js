// Real step data from app.py run_all(). Rebuild with mockups/make_data.py
window.SCENARIOS = [
 {
  "name": "Tree node types (CASE + subquery)",
  "setup": "Create table If Not Exists Tree (id int, p_id int)\nTruncate table Tree\ninsert into Tree (id, p_id) values ('1', NULL)\ninsert into Tree (id, p_id) values ('2', '1')\ninsert into Tree (id, p_id) values ('3', '1')\ninsert into Tree (id, p_id) values ('4', '2')\ninsert into Tree (id, p_id) values ('5', '2')",
  "code": "SELECT id,\n  CASE\n    WHEN p_id IS NULL THEN 'Root'\n    WHEN id IN (SELECT p_id FROM Tree) THEN 'Inner'\n    ELSE 'Leaf'\n  END AS type\nFROM Tree\nORDER BY id;",
  "statements": [
   {
    "text": "Create table If Not Exists Tree (id int, p_id int)",
    "phase": "setup"
   },
   {
    "text": "Truncate table Tree",
    "phase": "setup"
   },
   {
    "text": "insert into Tree (id, p_id) values ('1', NULL)",
    "phase": "setup"
   },
   {
    "text": "insert into Tree (id, p_id) values ('2', '1')",
    "phase": "setup"
   },
   {
    "text": "insert into Tree (id, p_id) values ('3', '1')",
    "phase": "setup"
   },
   {
    "text": "insert into Tree (id, p_id) values ('4', '2')",
    "phase": "setup"
   },
   {
    "text": "insert into Tree (id, p_id) values ('5', '2')",
    "phase": "setup"
   },
   {
    "text": "SELECT id,\n  CASE\n    WHEN p_id IS NULL THEN 'Root'\n    WHEN id IN (SELECT p_id FROM Tree) THEN 'Inner'\n    ELSE 'Leaf'\n  END AS type\nFROM Tree\nORDER BY id",
    "phase": "code"
   }
  ],
  "steps": [
   {
    "stmt": null,
    "title": "Starting tables",
    "explain": "Your schema ran. These are the tables before your code starts.",
    "kind": "start",
    "scope": "",
    "tables": [
     {
      "name": "Tree",
      "badge": null,
      "cols": [
       "id",
       "p_id"
      ],
      "rows": [
       {
        "v": [
         1,
         null
        ]
       },
       {
        "v": [
         2,
         1
        ]
       },
       {
        "v": [
         3,
         1
        ]
       },
       {
        "v": [
         4,
         2
        ]
       },
       {
        "v": [
         5,
         2
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 7,
    "title": "FROM Tree",
    "explain": "FROM runs first: start with every row of table Tree (5 rows).",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "id",
       "p_id"
      ],
      "rows": [
       {
        "v": [
         1,
         null
        ]
       },
       {
        "v": [
         2,
         1
        ]
       },
       {
        "v": [
         3,
         1
        ]
       },
       {
        "v": [
         4,
         2
        ]
       },
       {
        "v": [
         5,
         2
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 7,
    "title": "FROM Tree",
    "explain": "FROM runs first: start with every row of table Tree (5 rows). This is its own separate read of Tree: whatever this part does only shapes its own result, and the outer query's rows are not touched.",
    "kind": "query",
    "scope": "subquery in SELECT",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "id",
       "p_id"
      ],
      "rows": [
       {
        "v": [
         1,
         null
        ]
       },
       {
        "v": [
         2,
         1
        ]
       },
       {
        "v": [
         3,
         1
        ]
       },
       {
        "v": [
         4,
         2
        ]
       },
       {
        "v": [
         5,
         2
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 7,
    "title": "SELECT p_id",
    "explain": "SELECT now builds the output columns (p_id).  This is the result of subquery in SELECT: 5 rows.",
    "kind": "result",
    "scope": "subquery in SELECT",
    "tables": [
     {
      "name": "Result of subquery in SELECT",
      "badge": null,
      "cols": [
       "p_id"
      ],
      "rows": [
       {
        "v": [
         null
        ]
       },
       {
        "v": [
         1
        ]
       },
       {
        "v": [
         1
        ]
       },
       {
        "v": [
         2
        ]
       },
       {
        "v": [
         2
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "select",
     "cols": [
      {
       "name": "p_id",
       "sql": "p_id",
       "star": false,
       "window": false,
       "agg": false
      }
     ]
    }
   },
   {
    "stmt": 7,
    "title": "SELECT id, type",
    "explain": "SELECT now builds the output columns (id, type). CASE is checked top to bottom for each row, and the first WHEN that is true wins.",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "id",
       "type"
      ],
      "rows": [
       {
        "v": [
         1,
         "Root"
        ]
       },
       {
        "v": [
         2,
         "Inner"
        ]
       },
       {
        "v": [
         3,
         "Leaf"
        ]
       },
       {
        "v": [
         4,
         "Leaf"
        ]
       },
       {
        "v": [
         5,
         "Leaf"
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "select",
     "cols": [
      {
       "name": "id",
       "sql": "id",
       "star": false,
       "window": false,
       "agg": false
      },
      {
       "name": "type",
       "sql": "CASE WHEN p_id IS NULL THEN 'Root' WHEN id IN (SELECT p_id FROM Tree) THEN 'Inner' ELSE 'Leaf' END",
       "star": false,
       "window": false,
       "agg": false,
       "case": {
        "else": "'Leaf'",
        "operand": null,
        "branches": [
         {
          "when": "p_id IS NULL",
          "then": "'Root'",
          "offset": 0,
          "combine": null,
          "checks": [
           {
            "sql": "p_id IS NULL",
            "left": "p_id",
            "right": "NULL",
            "op": "IS"
           }
          ]
         },
         {
          "when": "id IN (SELECT p_id FROM Tree)",
          "then": "'Inner'",
          "offset": 4,
          "combine": null,
          "checks": [
           {
            "sql": "id IN (SELECT p_id FROM Tree)",
            "left": "id",
            "rest": "IN (SELECT p_id FROM Tree)",
            "list": [
             null,
             1,
             1,
             2,
             2
            ]
           }
          ]
         }
        ]
       }
      }
     ],
     "case_rows": [
      [
       1,
       1,
       null,
       null,
       1,
       1,
       1
      ],
      [
       0,
       0,
       1,
       null,
       1,
       1,
       2
      ],
      [
       0,
       0,
       1,
       null,
       null,
       null,
       3
      ],
      [
       0,
       0,
       2,
       null,
       null,
       null,
       4
      ],
      [
       0,
       0,
       2,
       null,
       null,
       null,
       5
      ]
     ]
    }
   },
   {
    "stmt": 7,
    "title": "ORDER BY id",
    "explain": "ORDER BY sorts the rows (ascending unless DESC; in MySQL, NULLs sort first when ascending). This is the final result: 5 rows.",
    "kind": "result",
    "scope": "",
    "tables": [
     {
      "name": "Final result",
      "badge": null,
      "cols": [
       "id",
       "type"
      ],
      "rows": [
       {
        "v": [
         1,
         "Root"
        ]
       },
       {
        "v": [
         2,
         "Inner"
        ]
       },
       {
        "v": [
         3,
         "Leaf"
        ]
       },
       {
        "v": [
         4,
         "Leaf"
        ]
       },
       {
        "v": [
         5,
         "Leaf"
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   }
  ]
 },
 {
  "name": "Raise, then department report (UPDATE + GROUP BY)",
  "setup": "CREATE TABLE Employee (id int primary key, name varchar(20), salary int, dept varchar(5), managerId int);\nINSERT INTO Employee VALUES (1,'Joe',70000,'A',3),(2,'Henry',80000,'B',4),(3,'Sam',60000,'A',NULL),(4,'Max',90000,'B',NULL),(5,'Amy',80000,'A',3);",
  "code": "UPDATE Employee SET salary = salary * 1.1 WHERE dept = 'A';\n\nSELECT dept, COUNT(*) AS n, AVG(salary) AS avg_pay\nFROM Employee\nWHERE salary > 60000\nGROUP BY dept\nHAVING n >= 2\nORDER BY avg_pay DESC;",
  "statements": [
   {
    "text": "CREATE TABLE Employee (id int primary key, name varchar(20), salary int, dept varchar(5), managerId int)",
    "phase": "setup"
   },
   {
    "text": "INSERT INTO Employee VALUES (1,'Joe',70000,'A',3),(2,'Henry',80000,'B',4),(3,'Sam',60000,'A',NULL),(4,'Max',90000,'B',NULL),(5,'Amy',80000,'A',3)",
    "phase": "setup"
   },
   {
    "text": "UPDATE Employee SET salary = salary * 1.1 WHERE dept = 'A'",
    "phase": "code"
   },
   {
    "text": "SELECT dept, COUNT(*) AS n, AVG(salary) AS avg_pay\nFROM Employee\nWHERE salary > 60000\nGROUP BY dept\nHAVING n >= 2\nORDER BY avg_pay DESC",
    "phase": "code"
   }
  ],
  "steps": [
   {
    "stmt": null,
    "title": "Starting tables",
    "explain": "Your schema ran. These are the tables before your code starts.",
    "kind": "start",
    "scope": "",
    "tables": [
     {
      "name": "Employee",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         70000,
         "A",
         3
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 2,
    "title": "WHERE dept = 'A'",
    "explain": "First MySQL finds the rows to update: WHERE dept = 'A'. 3 of 5 rows in Employee match (blue).",
    "kind": "query",
    "scope": "UPDATE row by row",
    "tables": [
     {
      "name": "Employee",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         70000,
         "A",
         3
        ],
        "m": "match"
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null
        ],
        "m": "match"
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3
        ],
        "m": "match"
       }
      ],
      "more": 0
     }
    ],
    "sql": "WHERE dept = 'A'",
    "detail": {
     "combine": null,
     "checks": [
      {
       "sql": "dept = 'A'",
       "left": "dept",
       "right": "'A'",
       "op": "="
      }
     ],
     "type": "filter",
     "rows": [
      [
       1,
       "A",
       "A"
      ],
      [
       0,
       "B",
       "A"
      ],
      [
       1,
       "A",
       "A"
      ],
      [
       0,
       "B",
       "A"
      ],
      [
       1,
       "A",
       "A"
      ]
     ]
    }
   },
   {
    "stmt": 2,
    "title": "Row 1 of 3",
    "explain": "Table row #1: salary: 70000 \u2192 77000.",
    "kind": "row",
    "scope": "UPDATE row by row",
    "tables": [
     {
      "name": "Employee",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ],
        "m": "current",
        "old": {
         "2": 70000
        }
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 2,
    "title": "Row 2 of 3",
    "explain": "Table row #3: salary: 60000 \u2192 66000.",
    "kind": "row",
    "scope": "UPDATE row by row",
    "tables": [
     {
      "name": "Employee",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ],
        "m": "changed",
        "old": {
         "2": 70000
        }
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         66000,
         "A",
         null
        ],
        "m": "current",
        "old": {
         "2": 60000
        }
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 2,
    "title": "Row 3 of 3",
    "explain": "Table row #5: salary: 80000 \u2192 88000.",
    "kind": "row",
    "scope": "UPDATE row by row",
    "tables": [
     {
      "name": "Employee",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ],
        "m": "changed",
        "old": {
         "2": 70000
        }
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         66000,
         "A",
         null
        ],
        "m": "changed",
        "old": {
         "2": 60000
        }
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         88000,
         "A",
         3
        ],
        "m": "current",
        "old": {
         "2": 80000
        }
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 2,
    "title": "UPDATE Employee SET salary = salary * 1.1 WHERE dept = 'A'",
    "explain": "UPDATE changed 3 rows in Employee. Changed cells are amber with the old value crossed out. (MySQL only counts rows whose values actually changed.)",
    "kind": "change",
    "scope": "",
    "tables": [
     {
      "name": "Employee",
      "badge": "changed",
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ],
        "m": "changed",
        "old": {
         "2": 70000
        }
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         66000,
         "A",
         null
        ],
        "m": "changed",
        "old": {
         "2": 60000
        }
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         88000,
         "A",
         3
        ],
        "m": "changed",
        "old": {
         "2": 80000
        }
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 3,
    "title": "FROM Employee",
    "explain": "FROM runs first: start with every row of table Employee (5 rows).",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         66000,
         "A",
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         88000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 3,
    "title": "WHERE salary > 60000",
    "explain": "WHERE checks each row and keeps only rows where the condition is true (NULL counts as not true). Kept 5 rows of 5; the crossed-out rows are dropped.",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         66000,
         "A",
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         88000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "filter",
     "combine": null,
     "checks": [
      {
       "sql": "salary > 60000",
       "left": "salary",
       "right": "60000",
       "op": ">"
      }
     ],
     "rows": [
      [
       1,
       77000,
       60000
      ],
      [
       1,
       80000,
       60000
      ],
      [
       1,
       66000,
       60000
      ],
      [
       1,
       90000,
       60000
      ],
      [
       1,
       88000,
       60000
      ]
     ]
    }
   },
   {
    "stmt": 3,
    "title": "GROUP BY dept",
    "explain": "GROUP BY gathers rows with the same dept into one group. Each color band below is one group. From here on, each group becomes a single row, so only the grouped columns and aggregates like COUNT() or SUM() can be shown.",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         77000,
         "A",
         3
        ],
        "g": 1
       },
       {
        "v": [
         3,
         "Sam",
         66000,
         "A",
         null
        ],
        "g": 1
       },
       {
        "v": [
         5,
         "Amy",
         88000,
         "A",
         3
        ],
        "g": 1
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ],
        "g": 2
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ],
        "g": 2
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "group",
     "keys": [
      "dept"
     ],
     "summary": {
      "name": "After GROUP BY",
      "badge": null,
      "cols": [
       "dept",
       "COUNT(*)",
       "AVG(salary)"
      ],
      "rows": [
       {
        "v": [
         "A",
         3,
         "77000.0000"
        ]
       },
       {
        "v": [
         "B",
         2,
         "85000.0000"
        ]
       }
      ],
      "more": 0
     },
     "aliases": {
      "COUNT(*)": "n",
      "AVG(salary)": "avg_pay"
     }
    }
   },
   {
    "stmt": 3,
    "title": "HAVING n >= 2",
    "explain": "HAVING filters whole groups (WHERE filters single rows, before grouping). Kept 2 groups; the crossed-out groups are dropped.",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "dept",
       "COUNT(*)"
      ],
      "rows": [
       {
        "v": [
         "A",
         3
        ]
       },
       {
        "v": [
         "B",
         2
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "filter",
     "groups": true,
     "combine": null,
     "checks": [
      {
       "sql": "COUNT(*) >= 2",
       "left": "COUNT(*)",
       "right": "2",
       "op": ">="
      }
     ],
     "rows": [
      [
       1,
       3,
       2
      ],
      [
       1,
       2,
       2
      ]
     ]
    }
   },
   {
    "stmt": 3,
    "title": "SELECT dept, n, avg_pay",
    "explain": "SELECT now builds the output columns (dept, n, avg_pay). ",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "dept",
       "n",
       "avg_pay"
      ],
      "rows": [
       {
        "v": [
         "A",
         3,
         "77000.0000"
        ]
       },
       {
        "v": [
         "B",
         2,
         "85000.0000"
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "select",
     "cols": [
      {
       "name": "dept",
       "sql": "dept",
       "star": false,
       "window": false,
       "agg": false
      },
      {
       "name": "n",
       "sql": "COUNT(*)",
       "star": false,
       "window": false,
       "agg": true
      },
      {
       "name": "avg_pay",
       "sql": "AVG(salary)",
       "star": false,
       "window": false,
       "agg": true
      }
     ]
    }
   },
   {
    "stmt": 3,
    "title": "ORDER BY avg_pay DESC",
    "explain": "ORDER BY sorts the rows (ascending unless DESC; in MySQL, NULLs sort first when ascending). This is the final result: 2 rows.",
    "kind": "result",
    "scope": "",
    "tables": [
     {
      "name": "Final result",
      "badge": null,
      "cols": [
       "dept",
       "n",
       "avg_pay"
      ],
      "rows": [
       {
        "v": [
         "B",
         2,
         "85000.0000"
        ]
       },
       {
        "v": [
         "A",
         3,
         "77000.0000"
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   }
  ]
 },
 {
  "name": "Employees and managers (LEFT JOIN)",
  "setup": "CREATE TABLE Employee (id int primary key, name varchar(20), salary int, dept varchar(5), managerId int);\nINSERT INTO Employee VALUES (1,'Joe',70000,'A',3),(2,'Henry',80000,'B',4),(3,'Sam',60000,'A',NULL),(4,'Max',90000,'B',NULL),(5,'Amy',80000,'A',3);",
  "code": "SELECT e.name AS employee, m.name AS manager\nFROM Employee e\nLEFT JOIN Employee m ON e.managerId = m.id\nWHERE e.salary > 65000\nORDER BY e.name;",
  "statements": [
   {
    "text": "CREATE TABLE Employee (id int primary key, name varchar(20), salary int, dept varchar(5), managerId int)",
    "phase": "setup"
   },
   {
    "text": "INSERT INTO Employee VALUES (1,'Joe',70000,'A',3),(2,'Henry',80000,'B',4),(3,'Sam',60000,'A',NULL),(4,'Max',90000,'B',NULL),(5,'Amy',80000,'A',3)",
    "phase": "setup"
   },
   {
    "text": "SELECT e.name AS employee, m.name AS manager\nFROM Employee e\nLEFT JOIN Employee m ON e.managerId = m.id\nWHERE e.salary > 65000\nORDER BY e.name",
    "phase": "code"
   }
  ],
  "steps": [
   {
    "stmt": null,
    "title": "Starting tables",
    "explain": "Your schema ran. These are the tables before your code starts.",
    "kind": "start",
    "scope": "",
    "tables": [
     {
      "name": "Employee",
      "badge": null,
      "cols": [
       "id",
       "name",
       "salary",
       "dept",
       "managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         70000,
         "A",
         3
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 2,
    "title": "FROM Employee AS e",
    "explain": "FROM runs first: start with every row of table Employee (5 rows).",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "e.id",
       "e.name",
       "e.salary",
       "e.dept",
       "e.managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         70000,
         "A",
         3
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   },
   {
    "stmt": 2,
    "title": "LEFT JOIN Employee AS m ON e.managerId = m.id",
    "explain": "JOIN pairs rows with matching rows of m. As a LEFT JOIN, rows from the left side with no match are kept anyway, with NULLs filled in. (Employee is the same stored table read a second time, under the name m.) 5 rows \u2192 5 rows.",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "e.id",
       "e.name",
       "e.salary",
       "e.dept",
       "e.managerId",
       "m.id",
       "m.name",
       "m.salary",
       "m.dept",
       "m.managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         70000,
         "A",
         3,
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4,
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null,
         null,
         null,
         null,
         null,
         null
        ]
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null,
         null,
         null,
         null,
         null,
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3,
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "join",
     "left": 5,
     "side": "LEFT",
     "table": "m",
     "combine": null,
     "checks": [
      {
       "sql": "e.managerId = m.id",
       "left": "e.managerId",
       "right": "m.id",
       "op": "="
      }
     ],
     "rows": [
      [
       1,
       3,
       3
      ],
      [
       1,
       4,
       4
      ],
      [
       null,
       null,
       null
      ],
      [
       null,
       null,
       null
      ],
      [
       1,
       3,
       3
      ]
     ]
    }
   },
   {
    "stmt": 2,
    "title": "WHERE e.salary > 65000",
    "explain": "WHERE checks each row and keeps only rows where the condition is true (NULL counts as not true). Kept 4 rows of 5; the crossed-out rows are dropped.",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "e.id",
       "e.name",
       "e.salary",
       "e.dept",
       "e.managerId",
       "m.id",
       "m.name",
       "m.salary",
       "m.dept",
       "m.managerId"
      ],
      "rows": [
       {
        "v": [
         1,
         "Joe",
         70000,
         "A",
         3,
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       },
       {
        "v": [
         2,
         "Henry",
         80000,
         "B",
         4,
         4,
         "Max",
         90000,
         "B",
         null
        ]
       },
       {
        "v": [
         3,
         "Sam",
         60000,
         "A",
         null,
         null,
         null,
         null,
         null,
         null
        ],
        "m": "dropped"
       },
       {
        "v": [
         4,
         "Max",
         90000,
         "B",
         null,
         null,
         null,
         null,
         null,
         null
        ]
       },
       {
        "v": [
         5,
         "Amy",
         80000,
         "A",
         3,
         3,
         "Sam",
         60000,
         "A",
         null
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "filter",
     "combine": null,
     "checks": [
      {
       "sql": "e.salary > 65000",
       "left": "e.salary",
       "right": "65000",
       "op": ">"
      }
     ],
     "rows": [
      [
       1,
       70000,
       65000
      ],
      [
       1,
       80000,
       65000
      ],
      [
       0,
       60000,
       65000
      ],
      [
       1,
       90000,
       65000
      ],
      [
       1,
       80000,
       65000
      ]
     ]
    }
   },
   {
    "stmt": 2,
    "title": "SELECT employee, manager",
    "explain": "SELECT now builds the output columns (employee, manager). ",
    "kind": "query",
    "scope": "",
    "tables": [
     {
      "name": "Rows at this stage",
      "badge": null,
      "cols": [
       "employee",
       "manager"
      ],
      "rows": [
       {
        "v": [
         "Joe",
         "Sam"
        ]
       },
       {
        "v": [
         "Henry",
         "Max"
        ]
       },
       {
        "v": [
         "Max",
         null
        ]
       },
       {
        "v": [
         "Amy",
         "Sam"
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null,
    "detail": {
     "type": "select",
     "cols": [
      {
       "name": "employee",
       "sql": "e.name",
       "star": false,
       "window": false,
       "agg": false
      },
      {
       "name": "manager",
       "sql": "m.name",
       "star": false,
       "window": false,
       "agg": false
      }
     ]
    }
   },
   {
    "stmt": 2,
    "title": "ORDER BY e.name",
    "explain": "ORDER BY sorts the rows (ascending unless DESC; in MySQL, NULLs sort first when ascending). This is the final result: 4 rows.",
    "kind": "result",
    "scope": "",
    "tables": [
     {
      "name": "Final result",
      "badge": null,
      "cols": [
       "employee",
       "manager"
      ],
      "rows": [
       {
        "v": [
         "Amy",
         "Sam"
        ]
       },
       {
        "v": [
         "Henry",
         "Max"
        ]
       },
       {
        "v": [
         "Joe",
         "Sam"
        ]
       },
       {
        "v": [
         "Max",
         null
        ]
       }
      ],
      "more": 0
     }
    ],
    "sql": null
   }
  ]
 }
];
