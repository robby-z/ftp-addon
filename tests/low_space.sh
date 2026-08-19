#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-reolink-ftps:test}"
test_dir="$(mktemp -d)"
container="reolink-ftps-low-space-$$"

cleanup() {
    docker rm -f "${container}" >/dev/null 2>&1 || true
    rm -rf "${test_dir}"
}
trap cleanup EXIT

mkdir -p "${test_dir}/media/ReolinkSSD" "${test_dir}/share" "${test_dir}/ssl" "${test_dir}/data"
cp tests/fixtures/options-low-space.json "${test_dir}/data/options.json"

docker run -d --name "${container}" \
    -p 2121:21 \
    -v "${test_dir}/media:/media" \
    -v "${test_dir}/share:/share" \
    -v "${test_dir}/ssl:/ssl:ro" \
    -v "${test_dir}/data:/data" \
    "${image}" >/dev/null

for _ in {1..30}; do
    if docker logs "${container}" 2>&1 | grep -q "FREE SPACE SAFETY STOP"; then
        break
    fi
    sleep 1
done

docker logs "${container}" 2>&1 | grep -q "FREE SPACE SAFETY STOP"
if python3 -c 'import ftplib; ftplib.FTP(timeout=2).connect("127.0.0.1", 2121)' 2>/dev/null; then
    echo "FTP service unexpectedly accepted a connection below the free-space threshold" >&2
    exit 1
fi

echo "Low-space service cutoff passed"
