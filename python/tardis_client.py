"""Small Python client for the TardisDB HTTP server (branch `server-revived`).

Only the standard library is used. The interface follows Python's DB-API
loosely (connect -> connection -> cursor -> execute/fetchall), because the
BranchBench2 adapter expects that shape later.

What the client adds on top of the raw HTTP API:
- one fresh database per connection (PUT /), dropped again on close();
- `%s` parameters, filled in as SQL literals;
- the current branch: statements get `VERSION <branch>` added automatically,
  because TardisDB has no "checkout";
- rows as tuples in the column order of the SELECT (the server's order changes);
- server errors (sent with HTTP 200 in "errormsg") raised as TardisError.
"""

import json
import re
import urllib.request

DEFAULT_URL = "http://localhost:5050"   # Mac port 5050 -> container port 5000
MASTER = "master"


class TardisError(Exception):
    """Error reported by TardisDB or raised by this client."""


# ---------------------------------------------------------------- HTTP layer

def _request(method, url, body=None, timeout=60):
    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------- SQL helpers

_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")


def _literal(value):
    """Turn a Python value into a TardisDB SQL literal."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        if re.search(r"\s", value) or "'" in value or ";" in value:
            # TardisDB's tokenizer ends a text literal at whitespace, and the
            # server splits the request body on ';'.
            raise TardisError(f"TardisDB text cannot contain spaces, quotes or ';': {value!r}")
        return f"'{value}'"
    raise TardisError(f"unsupported parameter type: {type(value).__name__}")


def fill_params(sql, params):
    """Replace each %s in sql with the next parameter as a literal."""
    if not params:
        return sql
    parts = sql.split("%s")
    if len(parts) - 1 != len(params):
        raise TardisError(f"{len(parts) - 1} placeholders but {len(params)} parameters")
    out = [parts[0]]
    for value, rest in zip(params, parts[1:]):
        out.append(_literal(value))
        out.append(rest)
    return "".join(out)


def add_version(statement, branch):
    """Add `VERSION <branch>` to every table of one statement.

    Handles TardisDB's grammar only: INSERT INTO t, UPDATE t, DELETE FROM t,
    SELECT ... FROM t [alias], u [alias] [WHERE ...]. Statements that already
    name a version, and statements on master, are returned unchanged.
    """
    if branch == MASTER or re.search(r"\bversion\b", statement, re.I):
        return statement
    s = statement
    for pattern in (r"^(\s*insert\s+into\s+\w+)", r"^(\s*update\s+\w+)", r"^(\s*delete\s+from\s+\w+)"):
        if re.match(pattern, s, re.I):
            return re.sub(pattern, rf"\1 version {branch}", s, count=1, flags=re.I)
    m = re.match(r"^(\s*select\s+.*?\s+from\s+)(.*?)(\s+where\s+.*)?$", s, re.I | re.S)
    if m:
        tables = []
        for item in m.group(2).split(","):
            words = item.split()
            words.insert(1, f"version {branch}")
            tables.append(" ".join(words))
        return m.group(1) + ", ".join(tables) + (m.group(3) or "")
    return s   # CREATE TABLE, CREATE BRANCH, ...: no version


def _select_names(statement):
    """Column names asked for in a SELECT list, without table aliases; None for *."""
    m = re.match(r"^\s*select\s+(.*?)\s+from\s", statement, re.I | re.S)
    if not m or m.group(1).strip() == "*":
        return None
    return [c.strip().split(".")[-1] for c in m.group(1).split(",")]


def _convert(value):
    if _INT.match(value):
        return int(value)
    if _FLOAT.match(value):
        return float(value)
    return value


# ---------------------------------------------------------------- DB-API-like classes

class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None   # list of column names of the last result
        self.rows = []
        self.timing = {}          # ms per phase of the last statement, from the server
        self.rowcount = -1

    def execute(self, sql, params=None):
        """Run one or more statements (separated by ';') on the current branch."""
        sql = fill_params(sql, params)
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        if not statements:
            raise TardisError("empty statement")
        body = ";".join(add_version(s, self.conn.branch) for s in statements) + ";"
        result = self.conn._post(body)
        self._load(result, statements[-1])
        return self

    def _load(self, result, last_statement):
        columns = [list(c.values())[0] for c in result.get("columns", [])]
        raw_rows = [[row[str(i)] for i in range(len(columns))] for row in result.get("content", [])]
        # The server's column order changes between runs: reorder to the SELECT list.
        wanted = _select_names(last_statement)
        if wanted and len(set(wanted)) == len(wanted) and sorted(wanted) == sorted(columns):
            idx = [columns.index(name) for name in wanted]
            columns = wanted
            raw_rows = [[r[i] for i in idx] for r in raw_rows]
        self.description = columns
        self.rows = [tuple(_convert(v) for v in r) for r in raw_rows]
        self.rowcount = len(self.rows)
        self.timing = {k[:-4]: v for k, v in result.items() if k.endswith("time")}

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class Connection:
    """One TardisDB database on the server, plus the branch statements run on."""

    def __init__(self, url=DEFAULT_URL, database=None):
        self.url = url.rstrip("/")
        self.branch = MASTER
        self._owns_db = database is None
        self.database = int(_request("PUT", self.url + "/")) if database is None else database
        self._closed = False

    def _post(self, body):
        if self._closed:
            # After DELETE the server silently falls back to database 0, so never reuse an id.
            raise TardisError("connection is closed")
        result = json.loads(_request("POST", f"{self.url}/{self.database}", body))
        if result.get("errormsg"):
            raise TardisError(result["errormsg"].strip().rstrip(";"))
        return result

    def cursor(self):
        return Cursor(self)

    def create_branch(self, name, parent=MASTER):
        self._post(f"create branch {name} from {parent};")

    def use_branch(self, name):
        """Run following statements on this branch (TardisDB has no checkout)."""
        self.branch = name

    def lineage(self):
        """Branch tree as returned by the server: {"nodes": [...], "links": [...]}."""
        return json.loads(_request("GET", f"{self.url}/{self.database}"))

    def commit(self):
        pass   # every statement is applied immediately

    def close(self):
        if not self._closed and self._owns_db:
            _request("DELETE", f"{self.url}/{self.database}")
        self._closed = True


def connect(url=DEFAULT_URL, database=None):
    """Open a connection. Without `database` a new, empty database is created."""
    return Connection(url, database)
