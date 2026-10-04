#!/usr/bin/env bash
# Do not start this unintentionally: bounded CAS-333 workload/concurrency matrix.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh process)/cas-333-soak}
iterations=${CAS333_SOAK_ITERATIONS:-5}
deadline_ms=${CAS333_SOAK_DEADLINE_MS:-15000}
terminal_deadline_ms=${CAS333_SOAK_TERMINAL_DEADLINE_MS:-5000}
mode=${CAS333_MODE:-native-headless}
artifact_set=${CAS333_ARTIFACT_SET:-minimal}
case "$mode" in native-headless|native-headful) ;; *) printf '%s\n' 'CAS333_MODE must be native-headless or native-headful' >&2; exit 2 ;; esac
case "$artifact_set" in minimal|full|growth) ;; *) printf '%s\n' 'CAS333_ARTIFACT_SET must be minimal, full, or growth' >&2; exit 2 ;; esac
parent=$(dirname "$destination")
mkdir -p "$parent"
staging=$(mktemp -d "$parent/.cas-333-soak-staging.XXXXXX")
backup=""
cleanup() { status=$?; trap - EXIT INT TERM; rm -rf -- "$staging"; if test -n "$backup" && test -e "$backup" && ! test -e "$destination"; then mv -- "$backup" "$destination"; fi; exit "$status"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Exactly one requested workload is run per cell; c1 is the sequential baseline.
for workload in success cancellation deadline failure; do
  for concurrency in 1 2 4; do
    run="$staging/matrix-$workload-c$concurrency"
    if test "$concurrency" = 1; then run="$staging/sequential-$workload-c1"; fi
    cell_deadline_ms=$deadline_ms
    if test "$workload" = deadline; then cell_deadline_ms=$terminal_deadline_ms; fi
    CAS333_ITERATIONS="$iterations" CAS333_DEADLINE_MS="$cell_deadline_ms" CAS333_CONCURRENCY="$concurrency" \
      scripts/browser/run-cas-333-profile.sh "$run" --mode "$mode" --artifact-set "$artifact_set" --workload "$workload" >/dev/null
  done
done
python3 - "$staging" > "$staging/summary.csv" <<'PY'
import csv, pathlib, sys
root = pathlib.Path(sys.argv[1])
writer = csv.writer(sys.stdout)
header = None
for workload in ("success", "cancellation", "deadline", "failure"):
    for concurrency in (1, 2, 4):
        directory = root / (f"sequential-{workload}-c1" if concurrency == 1 else f"matrix-{workload}-c{concurrency}")
        with (directory / "summary.csv").open(newline="") as source:
            rows = list(csv.reader(source))
        if len(rows) != 2:
            raise SystemExit(f"invalid child summary: {directory}")
        if header is None:
            header = ["workload_cell", "concurrency", *rows[0]]
            writer.writerow(header)
        elif rows[0] != header[2:]:
            raise SystemExit(f"incompatible child summary: {directory}")
        writer.writerow([workload, concurrency, *rows[1]])
PY
{
  printf 'CAS-333 bounded soak runner\n'
  printf 'mode=%s\nartifact_set=%s\nsequential_baseline=c1; iterations=%s\nsuccess_cancellation_deadline_ms=%s\ndeadline_stimulus_ms=%s\nconcurrency_matrix=1,2,4\n' "$mode" "$artifact_set" "$iterations" "$deadline_ms" "$terminal_deadline_ms"
  printf 'summary.csv combines all workload×concurrency cells with mode/artifact identity, elapsed and cancellation-to-return quantiles, and process peaks\n'
  printf 'each matrix cell invokes one requested workload; no nested all-workload profile runs\n'
  printf 'all target URLs are loopback; no public URLs are accepted\n'
  printf 'each child result and the top-level directory are atomically published\n'
} > "$staging/metadata.txt"
if test -e "$destination"; then backup="$parent/.cas-333-soak-backup.$$"; mv "$destination" "$backup"; fi
mv "$staging" "$destination"; staging="$parent/.cas-333-soak-complete.$$"
if test -n "$backup"; then rm -rf -- "$backup"; fi
trap - EXIT INT TERM
printf 'CAS-333 bounded soak written atomically to %s\n' "$destination"
