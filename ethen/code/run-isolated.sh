#!/usr/bin/env bash
# Linux qualification only; requires an existing test interpreter and rootlesskit.
set -euo pipefail
src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ "${1:-}" != --inside ]; then
  if [ "$#" -ne 2 ] || [[ "$1" != /* ]] || [[ "$2" != /* ]]; then
    echo 'usage: run-isolated.sh /new/owned/output /existing/test/bin/python' >&2
    exit 2
  fi
  p="$1"
  py="$2"
  test -x "$py"
  mkdir "$p"
  mkdir -p "$p/home/tmp" "$p/evidence" "$p/var-tmp"
  # This is the canonical runner's ignored duration cache, not a source edit.
  test -f "$src/test_durations.json" || printf '{}\n' > "$src/test_durations.json"
  exec rootlesskit --net=host bash "${BASH_SOURCE[0]}" --inside "$p" "$py"
fi
p="$2"
py="$3"
mount --bind "$p/var-tmp" /var/tmp
finish() {
  result=$?
  cg="$(cut -d: -f3 /proc/self/cgroup)"
  for metric in memory.max memory.peak memory.events cpu.max; do
    printf '%s\n' "$metric"
    cat "/sys/fs/cgroup$cg/$metric"
  done > "$p/evidence/cgroup.txt"
  cd /
  umount /var/tmp
  exit "$result"
}
trap finish EXIT
cd "$src"
write=write-file,remove-dir,remove-file,make-dir,make-reg,make-sock,make-fifo,make-sym,refer,truncate
unshare --net bash -c 'ip link set lo up; exec "$@"' _ setpriv --no-new-privs --landlock-access fs \
  --landlock-rule path-beneath:read-file,read-dir,execute:/ \
  --landlock-rule path-beneath:write-file:/dev/null \
  --landlock-rule path-beneath:$write:"$p/home" \
  --landlock-rule path-beneath:$write:"$p/evidence" \
  --landlock-rule path-beneath:$write:/var/tmp \
  --landlock-rule path-beneath:write-file,truncate:"$src/test_durations.json" \
  env -i PATH="$(dirname "$py"):/usr/bin:/bin" HOME="$p/home" \
  HERMES_HOME="$p/home/.hermes" HERMES_PYTHON="$py" HERMES_RUN_E2E=1 \
  PYTHONDONTWRITEBYTECODE=1 bash scripts/run_tests.sh -j 1 --file-retries 0 \
  --file-timeout 150 tests/ethen/test_coding_qualification.py \
  tests/tools/test_interrupt.py tests/acp_adapter/test_permissions.py \
  tests/acp_adapter/test_edit_approval.py tests/agent/test_interrupt_compat.py \
  --basetemp="$p/home/tmp/pytest" -pno:cacheprovider -v > "$p/evidence/tests.log" 2>&1
