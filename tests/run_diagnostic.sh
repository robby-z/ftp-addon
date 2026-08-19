#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-reolink-ftps:diagnostic}"
test_dir="$(mktemp -d)"
container="reolink-ftps-diagnostic-$$"

cleanup() {
    docker rm -f "${container}" >/dev/null 2>&1 || true
    docker run --rm --entrypoint /bin/chown \
        -v "${test_dir}:/cleanup" "${image}" \
        -R "$(id -u):$(id -g)" /cleanup >/dev/null 2>&1 || true
    rm -rf "${test_dir}"
}
trap cleanup EXIT

mkdir -p "${test_dir}/media/ReolinkSSD" "${test_dir}/data" "${test_dir}/ssl" "${test_dir}/share"
cp tests/fixtures/options.json "${test_dir}/data/options.json"

docker run -d --name "${container}" \
    -p 2121:21 \
    -p 30000-30019:30000-30019 \
    -v "${test_dir}/media:/media" \
    -v "${test_dir}/share:/share" \
    -v "${test_dir}/ssl:/ssl:ro" \
    -v "${test_dir}/data:/data" \
    "${image}" >/dev/null

sleep 2
python3 tests/diagnostic_login.py || true
sleep 1
docker logs "${container}" || true
docker exec "${container}" ps -ef || true
docker exec "${container}" sh -c \
    'grep -EH " = -1 |SIG[A-Z]+|unshare|clone|chroot|setuid|setgid|exit_group|exited|killed" /run/reolink-ftps/vsftpd.strace* 2>/dev/null | tail -500' || true
