"""Checks tardis_client.py against a running TardisDB server.

Run:  python3 test_client.py            (server on http://localhost:5050)
      python3 test_client.py http://localhost:5051
"""

import sys
import time

from tardis_client import TardisError, add_version, connect

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5050"
failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    failures += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n     expected {expected!r}\n     got      {got!r}"))


# 1. VERSION rewriting (no server needed)
check("rewrite insert", add_version("insert into t (k, v) values (1, 2)", "b1"),
      "insert into t version b1 (k, v) values (1, 2)")
check("rewrite update", add_version("update t set v = 3 where k = 1", "b1"),
      "update t version b1 set v = 3 where k = 1")
check("rewrite delete", add_version("delete from t where k = 1", "b1"),
      "delete from t version b1 where k = 1")
check("rewrite select with join",
      add_version("select a.k, b.w from t a, u b where a.k = b.k", "b1"),
      "select a.k, b.w from t version b1 a, u version b1 b where a.k = b.k")
check("master unchanged", add_version("select t.k from t t", "master"), "select t.k from t t")

# 2. Against the server
conn = connect(URL)
cur = conn.cursor()
print(f"     new database id {conn.database}")

cur.execute("create table users (id integer not null, name text not null)")
cur.execute("insert into users (id, name) values (%s, %s)", (1, "alice"))
cur.execute("insert into users (id, name) values (%s, %s)", (2, "bob"))
cur.execute("select u.id, u.name from users u")
check("master rows", sorted(cur.fetchall()), [(1, "alice"), (2, "bob")])
check("column order follows SELECT", cur.description, ["id", "name"])

conn.create_branch("b1")
conn.use_branch("b1")
cur.execute("update users set name = %s where id = %s", ("carol", 1))
cur.execute("insert into users (id, name) values (%s, %s)", (3, "dave"))
cur.execute("delete from users where id = %s", (2,))
cur.execute("select u.id, u.name from users u")
check("branch b1 sees its own changes", sorted(cur.fetchall()), [(1, "carol"), (3, "dave")])

conn.use_branch("master")
cur.execute("select u.id, u.name from users u")
check("master is untouched", sorted(cur.fetchall()), [(1, "alice"), (2, "bob")])

conn.create_branch("b2", parent="b1")
conn.use_branch("b2")
cur.execute("insert into users (id, name) values (%s, %s)", (4, "erin"))
cur.execute("select u.id from users u where u.id = %s", (1,))
check("nested branch b2 inherits b1", cur.fetchall(), [(1,)])
cur.execute("select u.id from users u")
check("nested branch b2 rows", sorted(cur.fetchall()), [(1,), (3,), (4,)])

for i in range(3, 15):
    conn.create_branch(f"b{i}")
nodes = [n["name"] for n in conn.lineage()["nodes"]]
check("15 branches exist (more than the old limit of 8)", len(nodes), 15)

conn.use_branch("master")
try:
    cur.execute("select u.id from users u where u.id > 1")
    check("unsupported SQL raises an error", "no error", "TardisError")
except TardisError as e:
    check("unsupported SQL raises an error", type(e).__name__, "TardisError")
    print(f"     server said: {e}")
try:
    cur.execute("insert into users (id, name) values (%s, %s)", (9, "a b"))
    check("text with a space is refused", "no error", "TardisError")
except TardisError as e:
    check("text with a space is refused", type(e).__name__, "TardisError")

t0 = time.perf_counter()
cur.execute("select u.id, u.name from users u where u.id = %s", (1,))
wall_ms = (time.perf_counter() - t0) * 1000
print(f"     one point read: {wall_ms:.2f} ms round trip; server: {cur.timing}")

conn.close()
try:
    cur.execute("select u.id from users u")
    check("closed connection refuses queries", "no error", "TardisError")
except TardisError:
    check("closed connection refuses queries", True, True)

print("\nALL OK" if failures == 0 else f"\n{failures} FAILED")
sys.exit(1 if failures else 0)
