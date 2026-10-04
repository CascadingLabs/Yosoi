#!/usr/bin/env bash
# Build one identity-bound image, then run the bounded CAS-333 workload matrix.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
environment= destination= image=${CAS333_IMAGE:-yosoi-cas333:local}
iterations=${CAS333_MATRIX_ITERATIONS:-1}; deadline_ms=${CAS333_MATRIX_DEADLINE_MS:-15000}; terminal_deadline_ms=${CAS333_MATRIX_TERMINAL_DEADLINE_MS:-5000}; artifact_set=${CAS333_MATRIX_ARTIFACT_SET:-full}
usage() { printf 'usage: %s --environment container-headless|container-headful --destination DIRECTORY [--iterations N] [--deadline-ms N] [--terminal-deadline-ms N] [--artifact-set NAME] [--image IMAGE]\n' "$0" >&2; }
while [ "$#" -gt 0 ]; do
 case "$1" in
  --environment|--destination|--iterations|--deadline-ms|--terminal-deadline-ms|--artifact-set|--image) [ "$#" -ge 2 ] || { usage; exit 64; }; key=${1#--}; value=$2; shift; case "$key" in environment) environment=$value;; destination) destination=$value;; iterations) iterations=$value;; deadline-ms) deadline_ms=$value;; terminal-deadline-ms) terminal_deadline_ms=$value;; artifact-set) artifact_set=$value;; image) image=$value;; esac ;;
  -h|--help) usage; exit 0;; *) usage; exit 64;; esac
 shift
done
case "$environment" in container-headless|container-headful) ;; *) usage; exit 64;; esac
[ -n "$destination" ] || { usage; exit 64; }
[[ "$iterations" =~ ^[1-9][0-9]*$ && "$deadline_ms" =~ ^[1-9][0-9]*$ && "$terminal_deadline_ms" =~ ^[1-9][0-9]*$ ]] || { printf 'iterations and deadline values must be positive integers\n' >&2; exit 64; }
parent=$(dirname "$destination"); mkdir -p "$parent"; staging=$(mktemp -d "$parent/.cas333-matrix.XXXXXX"); backup=
cleanup() { status=$?; trap - EXIT INT TERM; if [ "$status" -ne 0 ] && [ -n "$staging" ] && [ -d "$staging" ]; then failed="${destination}.failed.$$"; mv "$staging" "$failed"; staging=; printf 'failed matrix diagnostics retained at %s\n' "$failed" >&2; else rm -rf "$staging"; fi; if [ -n "$backup" ] && [ -e "$backup" ] && [ ! -e "$destination" ]; then mv "$backup" "$destination"; fi; exit "$status"; }; trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM
"$root/scripts/browser/cleanup-containers.sh" --check
if [ "${CAS333_CONTAINER_REUSE_IMAGE:-0}" != 1 ]; then
  "$root/scripts/browser/run-container.sh" --mode "$environment" --record "$staging/build.json" --image "$image" --build-only
fi
for workload in success cancellation deadline failure; do
 for concurrency in 1 2 4; do
  record="$staging/runs/${workload}-c${concurrency}.json"
  cell_deadline_ms=$deadline_ms
  if [ "$workload" = deadline ]; then cell_deadline_ms=$terminal_deadline_ms; fi
  CAS333_RUN_ID="matrix-${workload}-c${concurrency}-$$" "$root/scripts/browser/run-container.sh" --mode "$environment" --record "$record" --image "$image" --reuse-image --workload "$workload" --iterations "$iterations" --concurrency "$concurrency" --deadline-ms "$cell_deadline_ms" --artifact-set "$artifact_set"
 done
done
"$root/scripts/browser/cleanup-containers.sh" --check
python3 - "$staging" "$environment" "$iterations" "$deadline_ms" "$terminal_deadline_ms" "$artifact_set" <<'PY'
import csv,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); environment,iterations,deadline,terminal_deadline,artifact=sys.argv[2:]
records=[]
for path in sorted((root/'runs').glob('*.json')):
 record=json.loads(path.read_text())
 if record.get('schema') != 'cas333.container-identity.v4':
  continue
 if record.get('result')!='success' or record.get('artifacts',{}).get('cgroup_cleanup')!='disappeared': raise SystemExit(f'incomplete run record: {path.name}')
 runtime=record.get('container_runtime',{})
 for key in ('chromium_package_sha256','chromium_executable_sha256'):
  value=runtime.get(key)
  if (
      not isinstance(value,str) or len(value)!=64
      or any(character not in '0123456789abcdef' for character in value)
  ): raise SystemExit(f'invalid {key}: {path.name}')
 log=path.parent / record['artifacts']['container_log']
 attempts=[]
 if log.exists():
  for line in log.read_text(errors='replace').splitlines():
   try: value=json.loads(line)
   except json.JSONDecodeError: continue
   if isinstance(value,dict) and 'elapsed_ms' in value: attempts.append(value)
 cgroup=json.loads((path.parent / record['artifacts']['cgroup_json']).read_text())
 peak=cgroup.get('summary',{}).get('peak',{})
 def metric(name,key=None):
  value=peak.get(name,{}).get('value'); return value.get(key) if key and isinstance(value,dict) else value
 records.append((path.stem,record,attempts,metric('cpu_stat','usage_usec'),metric('memory_peak'),metric('pids_peak'),metric('io_stat'),metric('cpu_stat','nr_throttled'),metric('cpu_stat','throttled_usec'),metric('memory_events'),metric('pids_events')))
def quantile(values,q):
 values=sorted(values)
 if not values:return ''
 # nearest-rank quantile gives reproducible bounded-matrix summaries.
 return values[max(0, min(len(values)-1, (len(values)*q+99)//100-1))]
rows=[]
for name,record,attempts,cpu,memory,pids,io,throttled,throttled_us,memory_events,pids_events in records:
 elapsed=[a.get('elapsed_ms') for a in attempts if isinstance(a.get('elapsed_ms'),(int,float))]
 cancel=[a.get('cancellation_to_return_ms') for a in attempts if isinstance(a.get('cancellation_to_return_ms'),(int,float))]
 rows.append({'run':name,'workload':record['workload'],'concurrency':record['concurrency'],'container_exit':record['container']['exit_code'],'record_result':record['result'],'cleanup':record['artifacts']['cgroup_cleanup'],'attempt_count':len(attempts),'elapsed_p50_ms':quantile(elapsed,50),'elapsed_p95_ms':quantile(elapsed,95),'elapsed_p99_ms':quantile(elapsed,99),'cancellation_return_p50_ms':quantile(cancel,50),'cancellation_return_p95_ms':quantile(cancel,95),'cancellation_return_p99_ms':quantile(cancel,99),'cpu_usage_peak_usec':cpu or '','memory_peak_bytes':memory or '','pids_peak':pids or '','io_peak':json.dumps(io,sort_keys=True) if io is not None else '','cpu_nr_throttled_peak':throttled or '','cpu_throttled_peak_usec':throttled_us or '','memory_events_peak':json.dumps(memory_events,sort_keys=True) if memory_events is not None else '','pids_events_peak':json.dumps(pids_events,sort_keys=True) if pids_events is not None else '','finalization_results':json.dumps([a.get('finalization') for a in attempts],sort_keys=True),'attempt_cleanup_results':json.dumps([a.get('cleanup_state') for a in attempts],sort_keys=True)})
fields=list(rows[0])
with (root/'summary.csv').open('w',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
(root/'README.md').write_text('# CAS-333 container matrix\n\n' + f'Environment: `{environment}`  \nIterations per cell: `{iterations}`  \nSuccess/cancellation deadline: `{deadline}` ms  \nDeadline-stimulus bound: `{terminal_deadline}` ms  \nArtifact set: `{artifact}`\n\n' + 'The matrix covers success, cancellation, deadline, and failure at concurrency 1, 2, and 4. `summary.csv` contains attempt elapsed and cancellation-return nearest-rank p50/p95/p99 values, cgroup CPU/memory/PID/IO/throttling peaks/events, and container, finalization, and cleanup outcomes. Every record requires its labelled container and cgroup to have disappeared.\n')
PY
if [ -e "$destination" ]; then backup="$parent/.cas333-matrix-backup.$$"; mv "$destination" "$backup"; fi
mv "$staging" "$destination"; staging=
if [ -n "$backup" ]; then rm -rf "$backup"; backup=; fi
printf 'CAS-333 matrix published atomically: %s\n' "$destination"
