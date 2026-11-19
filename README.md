# SQL Stepper ERD Coach

## Purpose

SQL Stepper already shows students how a SQL query changes a table step by step. For my CS 452 final project, I plan to add an editor for entity relationship diagrams (ERDs). Students will draw their tables inside SQL Stepper and get help figuring out whether their design can answer the questions in an assignment.

## Plan

1. **Draw a diagram.** Let students add tables and columns, mark primary keys, and connect foreign keys to the columns they reference.
2. **Save and reopen it.** Write the tables, columns, keys, connections, and layout when a student saves. Read them back so the student can continue editing.
3. **Review it with AI.** Let students paste an assignment and ask the coach to review their diagram. The coach will point to a specific requirement, ask a guiding question, and offer a worked example on request. Students can revise the diagram and ask again.

For example, a blood bank assignment says staff can work at several locations. If a student's staff table has room for only one location per person, the coach could ask, “How would you record Maya working at two locations with a single staff record?”

## Current SQL Stepper tech stack

| Part | Technology |
| --- | --- |
| Browser interface | HTML, CSS, and plain JavaScript |
| Server | Python |
| SQL execution | MySQL 8, with PyMySQL connecting Python to the database |
| SQL parsing | SQLGlot |
| Existing AI chat | OpenRouter by default |

## Progress Log

11/17/26 (10m): created the project and devised a very basic design system.
