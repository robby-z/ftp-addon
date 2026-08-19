#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-reolink-ftps:test}"
test_dir="$(mktemp -d)"

cleanup() {
    rm -rf "${test_dir}"
}
trap cleanup EXIT

mkdir -p "${test_dir}/media" "${test_dir}/share" "${test_dir}/ssl" "${test_dir}/data"
cp tests/fixtures/options.json "${test_dir}/data/options.json"

if docker run --rm \
    -v "${test_dir}/media:/media" \
    -v "${test_dir}/share:/share" \
    -v "${test_dir}/ssl:/ssl:ro" \
    -v "${test_dir}/data:/data" \
    "${image}" >"${test_dir}/output.log" 2>&1; then
    echo "Container unexpectedly accepted missing storage anchor" >&2
    exit 1
fi

grep -Eq "Configured recording storage .* is unavailable.*Refusing to start" "${test_dir}/output.log"
test ! -e "${test_dir}/media/ReolinkSSD"
echo "Missing-anchor startup refusal passed"
