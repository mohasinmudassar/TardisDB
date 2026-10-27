#!/usr/bin/env bash
# Runs every tests/sql/*.sql file through the sql shell and compares the output
# with tests/sql/expected/<name>.out.
#
#   tests/run_sql_tests.sh              # check
#   UPDATE=1 tests/run_sql_tests.sh     # (re)record the expected output
#
# The sql binary defaults to build/sql; pass another path as the first argument.
set -u

# TardisDB prints the columns of a result row in a different order from run to
# run, so sort the values inside each "(a, b, c)" row before comparing.
normalize() {
    awk '/^\(.*\)$/ {
            n = split(substr($0, 2, length($0) - 2), v, ", ")
            for (i = 2; i <= n; i++) { x = v[i]; for (j = i - 1; j >= 1 && v[j] > x; j--) v[j+1] = v[j]; v[j+1] = x }
            line = "("; for (i = 1; i <= n; i++) line = line (i > 1 ? ", " : "") v[i]; print line ")"; next
         }
         { print }'
}

SQL_BIN=${1:-build/sql}
DIR="$(cd "$(dirname "$0")" && pwd)/sql"
mkdir -p "$DIR/expected"
failed=0

for file in "$DIR"/*.sql; do
    name=$(basename "$file" .sql)
    expected="$DIR/expected/$name.out"
    actual=$(timeout 60 "$SQL_BIN" < "$file" 2>&1)
    code=$?
    actual=$(printf '%s\n' "$actual" | normalize)

    if [ "$code" -ne 0 ]; then
        echo "FAIL $name: exit code $code"; failed=1; continue
    fi
    if grep -q "LLVM verifier" <<< "$actual"; then
        echo "FAIL $name: generated code is invalid"; failed=1; continue
    fi
    if [ "${UPDATE:-0}" = 1 ]; then
        printf '%s\n' "$actual" > "$expected"
        echo "rec  $name"; continue
    fi
    if ! diff -u "$expected" <(printf '%s\n' "$actual") > /dev/null 2>&1; then
        echo "FAIL $name: output differs from $expected"
        diff -u "$expected" <(printf '%s\n' "$actual") | head -20
        failed=1; continue
    fi
    echo "ok   $name"
done

exit $failed
