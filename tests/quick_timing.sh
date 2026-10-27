#!/usr/bin/env bash
# Rough per-statement timings for TardisDB's sql shell.
#   tests/quick_timing.sh [path/to/sql] [rows] [branches]
# Uses TARDIS_TIMING=1, which makes the shell print "[time] <us> us  <statement>"
# to stderr. Times are wall clock per statement and include JIT compilation.
set -u
SQL_BIN=${1:-build/sql}
ROWS=${2:-1000}
BRANCHES=${3:-100}
SQL=$(mktemp)

{
    echo "create table kv (k integer not null, v integer not null);"
    for i in $(seq 1 "$ROWS"); do echo "insert into kv (k, v) values ($i, 0);"; done
    for b in $(seq 1 "$BRANCHES"); do echo "create branch b$b from master;"; done
    for b in $(seq 1 "$BRANCHES"); do echo "update kv version b$b set v = $b where k = 1;"; done
    for b in $(seq 1 "$BRANCHES"); do echo "insert into kv version b$b (k, v) values ($((ROWS + b)), $b);"; done
    for b in $(seq 1 "$BRANCHES"); do echo "select x.v from kv version b$b x where x.k = 1;"; done
    for b in $(seq 1 "$BRANCHES"); do echo "select x.k, x.v from kv version b$b x;"; done
    echo "quit"
} > "$SQL"

echo "rows=$ROWS branches=$BRANCHES  (median per statement, incl. JIT compilation)"
TARDIS_TIMING=1 "$SQL_BIN" < "$SQL" 2>&1 >/dev/null | grep '^\[time\]' | awk '
    {
        us = $2; stmt = $0; sub(/^\[time\] [0-9]+ us  /, "", stmt)
        if      (stmt ~ /^create branch/)                 k = "create branch"
        else if (stmt ~ /^insert/ && stmt ~ / version /)  k = "insert in a branch"
        else if (stmt ~ /^insert/)                        k = "insert in master"
        else if (stmt ~ /^update/)                        k = "update in a branch"
        else if (stmt ~ /^select/ && stmt ~ / where /)    k = "point select in a branch"
        else if (stmt ~ /^select/)                        k = "full scan of a branch"
        else next
        n[k]++; t[k, n[k]] = us
        if (!(k in order)) { order[k] = ++m; name[m] = k }
    }
    END {
        for (o = 1; o <= m; o++) {
            k = name[o]; c = n[k]
            for (i = 1; i <= c; i++) a[i] = t[k, i]
            for (i = 2; i <= c; i++) { x = a[i]; for (j = i - 1; j >= 1 && a[j] > x; j--) a[j+1] = a[j]; a[j+1] = x }
            printf "%-26s %5d stmts   median %8.2f ms   max %8.2f ms\n", k, c, a[int((c + 1) / 2)] / 1000, a[c] / 1000
        }
    }'
rm -f "$SQL"
