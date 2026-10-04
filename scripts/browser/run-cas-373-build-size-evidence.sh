#!/usr/bin/env bash
# Collect paired clean/no-op build-time and release proxy-binary size evidence.
set -euo pipefail

usage() {
  printf '%s\n' \
    "usage: $0 DESTINATION [--source-root CHECKOUT] [--target-dir DISPOSABLE_TARGET_DIR] [--target TARGET_TRIPLE]" \
    '' \
    'DESTINATION must not exist and its parent must already exist.' \
    'The target directory must not exist. When omitted, a directory is made with mktemp.' >&2
}

if (($# == 1)) && { test "$1" = -h || test "$1" = --help; }; then
  usage
  exit 0
fi
if (($# == 0)); then
  usage
  exit 2
fi

destination_input=$1
shift
target_dir_input=''
target_triple=''
source_root_input=''
while (($#)); do
  case "$1" in
    --source-root)
      (($# >= 2)) || { usage; exit 2; }
      source_root_input=$2
      shift 2
      ;;
    --target-dir)
      (($# >= 2)) || { usage; exit 2; }
      target_dir_input=$2
      shift 2
      ;;
    --target)
      (($# >= 2)) || { usage; exit 2; }
      target_triple=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

script_root=$(cd "$(dirname "$0")/../.." && pwd -P)
if test -n "$source_root_input"; then
  root=$(cd "$source_root_input" && pwd -P)
else
  root=$script_root
fi
if ! test -f "$root/Cargo.toml" || ! test -f "$root/Cargo.lock"; then
  printf 'source root is not a locked Cargo workspace: %s\n' "$root" >&2
  exit 2
fi
destination=$(realpath -m -- "$destination_input")
destination_parent=$(dirname -- "$destination")
if ! test -d "$destination_parent"; then
  printf 'destination parent does not exist: %s\n' "$destination_parent" >&2
  exit 2
fi
if test -e "$destination" || test -L "$destination"; then
  printf 'destination already exists; refusing to replace it: %s\n' "$destination" >&2
  exit 2
fi

case "$destination/" in
  "$root"/*)
    printf 'destination must be outside the source tree so it cannot change source identity: %s\n' "$destination" >&2
    exit 2
    ;;
esac

staging=$(mktemp -d "$destination_parent/.cas-373-build-size-staging.XXXXXX")
target_dir=''
target_dir_owned=false
cleanup() {
  status=$?
  trap - EXIT INT TERM
  if test -n "$staging" && test -d "$staging"; then
    rm -rf -- "$staging"
  fi
  if test "$target_dir_owned" = true && test -n "$target_dir" && test -d "$target_dir"; then
    rm -rf -- "$target_dir"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if test -n "$target_dir_input"; then
  target_dir=$(realpath -m -- "$target_dir_input")
  target_parent=$(dirname -- "$target_dir")
  if ! test -d "$target_parent"; then
    printf 'target-directory parent does not exist: %s\n' "$target_parent" >&2
    exit 2
  fi
  if test -e "$target_dir" || test -L "$target_dir"; then
    printf 'target directory must be disposable and must not already exist: %s\n' "$target_dir" >&2
    exit 2
  fi
  case "$target_dir/" in
    "$root"/*)
      printf 'target directory must be outside the source tree: %s\n' "$target_dir" >&2
      exit 2
      ;;
  esac
  mkdir -- "$target_dir"
  target_dir_owned=true
else
  target_dir=$(mktemp -d "${TMPDIR:-/tmp}/cas-373-target.XXXXXX")
  target_dir_owned=true
fi

cd "$root"
command -v cargo >/dev/null
command -v rustc >/dev/null
command -v jj >/dev/null
command -v readlink >/dev/null
command -v sha256sum >/dev/null
command -v stat >/dev/null
command -v realpath >/dev/null

if test -z "$target_triple"; then
  target_triple=$(rustc -vV | awk '/^host:/ { print $2 }')
fi
if test -z "$target_triple"; then
  printf '%s\n' 'could not determine a target triple' >&2
  exit 2
fi

readonly profile=release
readonly package=yosoi-benchmarks
readonly feature_mode=no-default-features
readonly -a binaries=(profile_capture profile_browser)
readonly -a build_command=(
  cargo build
  --locked
  --offline
  --release
  --jobs 1
  --target "$target_triple"
  --target-dir "$target_dir"
  --package "$package"
  --no-default-features
  --bin profile_capture
  --bin profile_browser
  --verbose
  --verbose
)

shell_join() {
  printf '%q ' "$@"
  printf '\n'
}

elapsed_build() {
  local label=$1
  local start_ns end_ns status
  start_ns=$(date +%s%N)
  set +e
  CARGO_BUILD_JOBS=1 "${build_command[@]}" > "$staging/$label-build.log" 2>&1
  status=$?
  set -e
  end_ns=$(date +%s%N)
  printf '%s\n' "$start_ns" > "$staging/$label-start-unix-ns.txt"
  printf '%s\n' "$end_ns" > "$staging/$label-end-unix-ns.txt"
  printf '%s\n' "$((end_ns - start_ns))" > "$staging/$label-wall-ns.txt"
  printf '%s\n' "$status" > "$staging/$label-status.txt"
  return "$status"
}

source_tree_sha256() {
  local file_list=$target_dir/.cas-373-source-files
  local hash_stream=$target_dir/.cas-373-source-hash-stream
  local path executable digest
  jj file list -r @ | LC_ALL=C sort -u > "$file_list"
  : > "$hash_stream"
  while IFS= read -r path || test -n "$path"; do
    if test -z "$path"; then
      continue
    fi
    case "$path" in
      /*|..|../*|*/../*)
        printf '%s\n' 'JJ returned a source path outside the workspace' >&2
        return 1
        ;;
    esac
    if test -L "$path"; then
      digest=$(readlink -z -- "$path" | sha256sum | awk '{ print $1 }')
      printf 'symlink\0%s\0%s\0' "$path" "$digest" >> "$hash_stream"
    elif test -f "$path"; then
      executable=false
      if test -x "$path"; then
        executable=true
      fi
      digest=$(sha256sum -- "$path" | awk '{ print $1 }')
      printf 'file\0%s\0%s\0%s\0' "$path" "$executable" "$digest" >> "$hash_stream"
    else
      printf 'JJ source entry is not a regular file or symlink\n' >&2
      return 1
    fi
  done < "$file_list"
  digest=$(sha256sum -- "$hash_stream" | awk '{ print $1 }')
  rm -f -- "$file_list" "$hash_stream"
  printf '%s\n' "$digest"
}

source_commit=$(jj log -r @ --no-graph -T 'commit_id ++ "\n"')
source_change=$(jj log -r @ --no-graph -T 'change_id ++ "\n"')
source_parents=$(jj log -r '@-' --no-graph -T 'commit_id ++ "\n"')
jj_status=$(jj status --color never)
printf '%s\n' "$jj_status" > "$staging/jj-status.txt"
source_tree_digest=$(source_tree_sha256)
sha256sum Cargo.lock > "$staging/cargo-lock.sha256"

rustc -vV > "$staging/rustc-version.txt"
cargo -vV > "$staging/cargo-version.txt"
rustc --print cfg --target "$target_triple" > "$staging/rustc-target-cfg.txt"
{
  printf 'RUSTFLAGS=%s\n' "${RUSTFLAGS-}"
  printf 'CARGO_ENCODED_RUSTFLAGS=%s\n' "${CARGO_ENCODED_RUSTFLAGS-}"
  printf 'RUSTC_WRAPPER=%s\n' "${RUSTC_WRAPPER-}"
  printf 'RUSTC_WORKSPACE_WRAPPER=%s\n' "${RUSTC_WORKSPACE_WRAPPER-}"
  printf 'CC=%s\n' "${CC-}"
  printf 'CXX=%s\n' "${CXX-}"
  printf 'LD=%s\n' "${LD-}"
  printf 'LDFLAGS=%s\n' "${LDFLAGS-}"
  env | LC_ALL=C sort | awk -F= '/^CARGO_TARGET_[A-Z0-9_]+_(LINKER|RUSTFLAGS)=/'
} > "$staging/linker-flags-environment.txt"

{
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'source_root=%s\n' "$root"
  printf 'jj_commit_id=%s\n' "$source_commit"
  printf 'jj_change_id=%s\n' "$source_change"
  printf 'jj_parent_commit_ids=%s\n' "$(printf '%s' "$source_parents" | paste -sd, -)"
  printf 'source_tree_sha256=%s\n' "$source_tree_digest"
  printf 'source_tree_hash_scope=JJ revision files including non-ignored eligible untracked files; path, file kind, executable bit, and content or symlink-target SHA-256\n'
  printf 'cargo_lock_sha256=%s\n' "$(awk '{ print $1 }' "$staging/cargo-lock.sha256")"
  printf 'package=%s\n' "$package"
  printf 'profile=%s\n' "$profile"
  printf 'feature_mode=%s\n' "$feature_mode"
  printf 'target_triple=%s\n' "$target_triple"
  printf 'cargo_jobs=1\n'
  printf 'cargo_locked=true\n'
  printf 'cargo_offline=true\n'
  printf 'artifact_role=benchmark_executable_proxy\n'
  printf 'production_binary_exists=false\n'
  printf 'artifact_warning=profile_capture and profile_browser are benchmark executable proxies, not production binaries\n'
} > "$staging/metadata.txt"
shell_join "${build_command[@]}" > "$staging/build-command.txt"
free -h > "$staging/preflight-free.txt"
ps -eo pid,ppid,stat,%cpu,%mem,rss,vsz,etime,comm --sort=-rss > "$staging/preflight-processes.txt"
uname -a > "$staging/uname.txt"

elapsed_build clean
elapsed_build no-op-incremental

source_tree_digest_after=$(source_tree_sha256)
if test "$source_tree_digest_after" != "$source_tree_digest"; then
  printf '%s\n' 'source tree changed during measurement; refusing to publish evidence' >&2
  exit 1
fi
source_commit_after=$(jj log -r @ --no-graph -T 'commit_id ++ "\n"')
source_change_after=$(jj log -r @ --no-graph -T 'change_id ++ "\n"')
if test "$source_commit_after" != "$source_commit" || test "$source_change_after" != "$source_change"; then
  printf '%s\n' 'JJ source identity changed during measurement; refusing to publish evidence' >&2
  exit 1
fi

printf 'artifact\trole\tbytes\tsha256\n' > "$staging/artifacts.tsv"
for binary in "${binaries[@]}"; do
  artifact="$target_dir/$target_triple/$profile/$binary"
  if ! test -f "$artifact"; then
    printf 'expected artifact was not produced: %s\n' "$artifact" >&2
    exit 1
  fi
  bytes=$(stat -c '%s' -- "$artifact")
  digest=$(sha256sum "$artifact" | awk '{ print $1 }')
  printf '%s\tbenchmark_executable_proxy\t%s\t%s\n' "$binary" "$bytes" "$digest" >> "$staging/artifacts.tsv"
done

{
  printf 'measurement\twall_ns\tstatus\n'
  printf 'clean\t%s\t%s\n' "$(<"$staging/clean-wall-ns.txt")" "$(<"$staging/clean-status.txt")"
  printf 'no-op-incremental\t%s\t%s\n' "$(<"$staging/no-op-incremental-wall-ns.txt")" "$(<"$staging/no-op-incremental-status.txt")"
} > "$staging/timings.tsv"

rm -rf -- "$target_dir"
target_dir=''
target_dir_owned=false
mv --update=none-fail --no-copy --no-target-directory -- "$staging" "$destination"
staging=''
trap - EXIT INT TERM
printf 'CAS-373 build/size evidence published atomically to %s\n' "$destination"
