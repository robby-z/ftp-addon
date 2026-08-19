#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-reolink-ftps:test}"
test_dir="$(mktemp -d)"
container="reolink-ftps-test-$$"

cleanup() {
    docker rm -f "${container}" >/dev/null 2>&1 || true
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

if ! python3 tests/integration_ftps.py; then
    docker logs "${container}"
    exit 1
fi

docker exec "${container}" test -f /data/tls/selfsigned.crt
docker exec "${container}" test -f /media/ReolinkSSD/reolink/front/viewer-visible.mp4

docker stop "${container}" >/dev/null
docker start "${container}" >/dev/null
python3 tests/integration_ftps.py

echo "Container restart and persistent-certificate integration checks passed"
