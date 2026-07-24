"""t-string helper (PEP 750) → parameterized SQL for sqlite3.

Converts a `t"..."` into `(sql, params)` where **every** interpolation travels as a
positional parameter `?`, never as text. SQL injection is impossible by construction:
values are never concatenated into the SQL.

    >>> tid = "42"
    >>> sql(t"SELECT * FROM tasks WHERE id = {tid}")
    ('SELECT * FROM tasks WHERE id = ?', ['42'])

Rule: only *values* are interpolated. *Identifiers* (table, column, `ORDER BY ... DESC`)
must be static template text — a SQL parameter cannot be an identifier.
"""

from string.templatelib import Interpolation, Template


def sql(template: Template) -> tuple[str, list[object]]:
    parts: list[str] = []
    params: list[object] = []
    for item in template:
        match item:
            case Interpolation():
                parts.append("?")
                params.append(item.value)
            case str():
                parts.append(item)
    return "".join(parts), params
