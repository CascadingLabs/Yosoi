#!/usr/bin/env bash
# Run one bounded CAS-333 container profile with an identity-bound image.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
mode= record= workload=success iterations=1 concurrency=1 deadline_ms=5000 artifact_set=full
image=${CAS333_IMAGE:-yosoi-cas333:local}
image_action=build
base_image_reference=voidcrawl-headful:local
expected_base_image_id=sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a

usage() { printf 'usage: %s --mode container-headless|container-headful --record FILE [--workload success|cancellation|deadline|failure] [--iterations N] [--concurrency N] [--deadline-ms N] [--artifact-set NAME] [--build|--reuse-image|--build-only]\n' "$0" >&2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    container-headless|container-headful) [ -z "$mode" ] || { usage; exit 64; }; mode=$1 ;;
    --mode|--record|--workload|--iterations|--concurrency|--deadline-ms|--artifact-set|--image) [ "$#" -ge 2 ] || { usage; exit 64; }; key=${1#--}; value=$2; shift; case "$key" in mode) mode=$value;; record) record=$value;; workload) workload=$value;; iterations) iterations=$value;; concurrency) concurrency=$value;; deadline-ms) deadline_ms=$value;; artifact-set) artifact_set=$value;; image) image=$value;; esac ;;
    --build) image_action=build ;;
    --reuse-image) image_action=reuse ;;
    --build-only) image_action=build-only ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 64 ;;
  esac
  shift
done
[ -n "$mode" ] || { usage; exit 64; }
[ -n "$record" ] || record="/tmp/cas333-${mode}-${workload}-$$.json"
mkdir -p "$(dirname "$record")"
case "$mode" in container-headless|container-headful) ;; *) usage; exit 64;; esac
case "$workload" in success|cancellation|deadline|failure) ;; *) usage; exit 64;; esac
[[ "$iterations" =~ ^[1-9][0-9]*$ && "$concurrency" =~ ^[1-9][0-9]*$ && "$deadline_ms" =~ ^[1-9][0-9]*$ ]] || { printf 'iterations, concurrency, and deadline-ms must be positive integers\n' >&2; exit 64; }
[[ "$artifact_set" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { printf 'artifact-set must be an identifier\n' >&2; exit 64; }

resolve_change_id() {
  jj -R "$root" log -r @ --no-graph -T 'change_id.shortest(12) ++ "\n"' 2>/dev/null \
    || git -C "$root" rev-parse --short=12 HEAD 2>/dev/null \
    || printf unknown
}
run_id=${CAS333_RUN_ID:-"${mode}-${workload}-$(date -u +%Y%m%dT%H%M%SZ)-$$"}
change_id=${CAS333_CHANGE_ID:-$(resolve_change_id)}
[[ "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ && "$change_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { printf 'CAS333_RUN_ID and CAS333_CHANGE_ID must be Docker-label-safe identifiers\n' >&2; exit 64; }
context= container= log_path="${record%.json}.container.log" cgroup_json="${record%.json}.cgroup.json" cgroup_csv="${record%.json}.cgroup.csv"
log_tmp="${log_path}.tmp.$$"; image_id= base_id= platform= init_pid= container_exit= cgroup_cleanup_state=unknown
docker_server_version= docker_storage_driver= docker_cgroup_version= docker_cgroup_driver= docker_default_runtime= chromium_version= chromium_package_sha256= chromium_executable_sha256=
result=blocker stage=prepare log_pid= sampler_pid= source_hash= provider_source_hash= fixture_hash= build_hash= elapsed_ms=0
started_ns=$(date +%s%N)
seccomp_hash=$(sha256sum "$root/docker/browser/seccomp-chrome.json" | awk '{print $1}')

atomic_record() { python3 - "$record" "$mode" "$workload" "$iterations" "$concurrency" "$deadline_ms" "$artifact_set" "$result" "$stage" "$image_id" "$base_id" "$platform" "$seccomp_hash" "$source_hash" "$provider_source_hash" "$fixture_hash" "$build_hash" "$run_id" "$change_id" "$init_pid" "$container_exit" "$log_path" "$cgroup_json" "$cgroup_csv" "$cgroup_cleanup_state" "$elapsed_ms" "$docker_server_version" "$docker_storage_driver" "$docker_cgroup_version" "$docker_cgroup_driver" "$docker_default_runtime" "$chromium_version" "$chromium_package_sha256" "$chromium_executable_sha256" <<'PY'
import json, os, pathlib, sys, tempfile
(a, mode, workload, iterations, concurrency, deadline, artifact_set, result, stage, image_id, base_id, platform, seccomp, source, provider, fixture, build, run_id, change, pid, exit_code, log, cgroup, csv, cleanup, elapsed, docker_server, storage_driver, cgroup_version, cgroup_driver, default_runtime, chromium, chromium_package, chromium_executable) = sys.argv[1:]
p = {
    "schema": "cas333.container-identity.v4",
    "mode": mode,
    "workload": workload,
    "iterations": int(iterations),
    "concurrency": int(concurrency),
    "deadline_ms": int(deadline),
    "artifact_set": artifact_set,
    "result": result,
    "stage": stage,
    "elapsed_ms": int(elapsed),
    "labels": {
        "com.cascadinglabs.yosoi.cas333": "true",
        "com.cascadinglabs.yosoi.cas333.run_id": run_id,
        "com.cascadinglabs.yosoi.cas333.change_id": change,
    },
    "image_id": image_id or None,
    "base_image_id": base_id or None,
    "platform": platform or None,
    "source_sha256": source or None,
    "provider_source_sha256": provider or None,
    "fixture_sha256": fixture or None,
    "build_sha256": build or None,
    "container_runtime": {"docker_server_version": docker_server or None, "storage_driver": storage_driver or None, "cgroup_version": cgroup_version or None, "cgroup_driver": cgroup_driver or None, "default_oci_runtime": default_runtime or None, "chromium_version": chromium or None, "chromium_package_sha256": chromium_package or None, "chromium_executable_sha256": chromium_executable or None},
    "runtime": {
        "user": "10001:10001",
        "network": "none",
        "resources": {"shm_size": "1g", "memory": "4g", "memory_swap": "4g", "cpus": "2", "pids": 2048},
        "security": {"read_only": True, "tmpfs": "/tmp:rw,nosuid,nodev,noexec,size=1g", "cap_drop": ["ALL"], "no_new_privileges": True, "seccomp_sha256": seccomp, "chrome_sandbox_required": True},
    },
    "container": {"init_pid": int(pid) if pid.isdigit() else None, "exit_code": int(exit_code) if exit_code.lstrip('-').isdigit() else None},
    "artifacts": {"container_log": pathlib.Path(log).name, "cgroup_json": pathlib.Path(cgroup).name, "cgroup_csv": pathlib.Path(csv).name, "cgroup_cleanup": cleanup},
}
out=pathlib.Path(a); out.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile("w", dir=out.parent, prefix=out.name+".", delete=False, encoding="utf-8") as f: json.dump(p,f,sort_keys=True,indent=2); f.write("\n"); name=f.name
os.replace(name,out)
PY
}
remove_container() { local ids id; ids=$(docker ps -aq --filter "name=^/${container}$" --filter 'label=com.cascadinglabs.yosoi.cas333=true' 2>/dev/null || true); while IFS= read -r id; do [[ "$id" =~ ^[[:xdigit:]]{12,64}$ ]] && docker rm -f -- "$id" >/dev/null 2>&1 || true; done <<<"$ids"; }
cleanup() { local status=$?; trap - EXIT INT TERM; remove_container; [ -n "$log_pid" ] && wait "$log_pid" 2>/dev/null || true; [ -n "$sampler_pid" ] && wait "$sampler_pid" 2>/dev/null || true; [ -f "$log_tmp" ] && mv -f "$log_tmp" "$log_path" || true; [ -n "$context" ] && rm -rf "$context"; elapsed_ms=$(( ($(date +%s%N) - started_ns) / 1000000 )); atomic_record; exit "$status"; }
trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM

tree_hash() { python3 - "$1" <<'PY'
import hashlib, os, pathlib, sys
root=pathlib.Path(sys.argv[1]); ignored={".git",".jj",".pi",".agents","target","results","keys","secrets",".voidcrawl",".yosoi","node_modules","coverage","dist","build",".ssh",".aws"}; h=hashlib.sha256()
for current, dirs, files in os.walk(root):
 dirs[:]=sorted(d for d in dirs if d not in ignored and d != '.env' and not d.startswith('.env.'))
 for name in sorted(files):
  if name == '.env' or name.startswith('.env.') or name.endswith(('.key','.pem','.p12','.pfx','.crt','.age')): continue
  p=pathlib.Path(current,name); r=p.relative_to(root).as_posix().encode(); h.update(len(r).to_bytes(8,'big')); h.update(r)
  try:
   with p.open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
  except FileNotFoundError: pass
print(h.hexdigest())
PY
}
image_labels() { local labels; labels=$(docker image inspect "$image" --format '{{json .Config.Labels}}') || return 1; python3 - "$labels" "$source_hash" "$provider_source_hash" "$fixture_hash" "$build_hash" "$expected_base_image_id" <<'PY'
import json,sys
try: labels=json.loads(sys.argv[1])
except ValueError: sys.exit(1)
keys=('com.cascadinglabs.yosoi.cas333.source_sha256','com.cascadinglabs.yosoi.cas333.provider_source_sha256','com.cascadinglabs.yosoi.cas333.fixture_sha256','com.cascadinglabs.yosoi.cas333.build_sha256','com.cascadinglabs.yosoi.cas333.base_image_id')
sys.exit(0 if all(labels.get(k)==v for k,v in zip(keys,sys.argv[2:])) else 1)
PY
}
verify_tagged_base() { base_id=$(docker image inspect "$base_image_reference" --format '{{.Id}}') || return 1; [ "$base_id" = "$expected_base_image_id" ] || { printf 'refusing build: %s resolves to %s, expected %s\n' "$base_image_reference" "$base_id" "$expected_base_image_id" >&2; return 1; }; }
image_inherits_base() { local base_layers image_layers; base_layers=$(docker image inspect "$expected_base_image_id" --format '{{json .RootFS.Layers}}') || return 1; image_layers=$(docker image inspect "$image" --format '{{json .RootFS.Layers}}') || return 1; python3 - "$base_layers" "$image_layers" <<'PY' || return 1
import json,sys
base=json.loads(sys.argv[1]); image=json.loads(sys.argv[2])
sys.exit(0 if image[:len(base)] == base else 1)
PY
base_id=$expected_base_image_id
}
"$root/scripts/browser/cleanup-containers.sh" --check
source_hash=$(tree_hash "$root"); provider_source_hash=$(tree_hash "$root/crates/voidcrawl"); fixture_hash=$(tree_hash "$root/benchmarks/fixtures/browser-capture")
build_hash=$(printf '%s\n%s\n%s\n' "$source_hash" "$provider_source_hash" "$fixture_hash" | sha256sum | awk '{print $1}')
if [ "$image_action" = build ] || [ "$image_action" = build-only ]; then
 verify_tagged_base
 context=$(mktemp -d "${TMPDIR:-/tmp}/cas333-container-context.XXXXXX"); "$root/scripts/browser/prepare-container-context.sh" "$context" >/dev/null
 docker build --pull=false --tag "$image" --label "com.cascadinglabs.yosoi.cas333.source_sha256=$source_hash" --label "com.cascadinglabs.yosoi.cas333.provider_source_sha256=$provider_source_hash" --label "com.cascadinglabs.yosoi.cas333.fixture_sha256=$fixture_hash" --label "com.cascadinglabs.yosoi.cas333.build_sha256=$build_hash" --label "com.cascadinglabs.yosoi.cas333.base_image_id=$expected_base_image_id" --file "$context/docker/browser/Dockerfile" "$context"
elif ! image_labels; then printf 'refusing image reuse: image identity does not match exact source hashes and base image\n' >&2; exit 1; fi
image_labels || { printf 'refusing image: identity labels do not match exact source hashes and base image\n' >&2; exit 1; }
image_inherits_base || { printf 'refusing image: layer ancestry does not match expected base image\n' >&2; exit 1; }
image_identity=$(docker image inspect "$image" --format '{{.Id}}|{{.Os}}/{{.Architecture}}'); image_id=${image_identity%%|*}; platform=${image_identity#*|}
docker_identity=$(docker info --format '{{.ServerVersion}}|{{.Driver}}|{{.CgroupVersion}}|{{.CgroupDriver}}|{{.DefaultRuntime}}')
IFS='|' read -r docker_server_version docker_storage_driver docker_cgroup_version docker_cgroup_driver docker_default_runtime <<<"$docker_identity"
chromium_version=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true --entrypoint /bin/cat "$image" /usr/share/cas333/chromium-version.txt)
chromium_package_sha256=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true --entrypoint /bin/cat "$image" /usr/share/cas333/chromium-package-sha256.txt)
chromium_executable_sha256=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true --entrypoint /bin/cat "$image" /usr/share/cas333/chromium-executable-sha256.txt)
if [ "$image_action" = build-only ]; then result=success; stage=build_complete; exit 0; fi
container="cas333-${mode}-${run_id}"; container=${container:0:120}; stage=create
docker create --name "$container" --label com.cascadinglabs.yosoi.cas333=true --label "com.cascadinglabs.yosoi.cas333.run_id=$run_id" --label "com.cascadinglabs.yosoi.cas333.change_id=$change_id" --user 10001:10001 --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,noexec,size=1g --shm-size=1g --pids-limit=2048 --memory=4g --memory-swap=4g --cpus=2 --cap-drop ALL --security-opt no-new-privileges:true --security-opt "seccomp=$root/docker/browser/seccomp-chrome.json" --env CHROME_NO_SANDBOX=0 "$image" "$mode" --workload "$workload" --iterations "$iterations" --concurrency "$concurrency" --deadline-ms "$deadline_ms" --artifact-set "$artifact_set" >/dev/null
stage=run; docker start "$container" >/dev/null; docker logs --follow "$container" >"$log_tmp" 2>&1 & log_pid=$!; init_pid=$(docker inspect --format '{{.State.Pid}}' "$container"); [[ "$init_pid" =~ ^[1-9][0-9]*$ ]] || { printf 'container init PID was invalid\n' >&2; exit 1; }
python3 "$root/scripts/browser/sample_cgroup_v2.py" --pid "$init_pid" --output "$cgroup_json" --csv "$cgroup_csv" --cleanup-grace-ms 10000 & sampler_pid=$!
container_exit=$(docker wait "$container"); [[ "$container_exit" =~ ^[0-9]+$ ]] || exit 1
[ "$container_exit" -eq 0 ] || { stage=container_exit; exit 1; }
remove_container; if ! wait "$sampler_pid"; then stage=cgroup_cleanup; exit 1; fi; sampler_pid=
cgroup_cleanup_state=$(python3 - "$cgroup_json" <<'PY'
import json,sys
try: print('disappeared' if json.load(open(sys.argv[1])).get('cleanup',{}).get('disappeared') else 'not_disappeared')
except (OSError,ValueError): print('not_disappeared')
PY
)
[ "$cgroup_cleanup_state" = disappeared ] || { stage=cgroup_cleanup; exit 1; }
"$root/scripts/browser/cleanup-containers.sh" --check; result=success; stage=complete
