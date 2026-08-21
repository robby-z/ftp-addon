#!/usr/bin/env bash
set -Eeuo pipefail

image="${1:-reolink-ftps:test}"
test_dir="$(mktemp -d)"
container="reolink-ftps-ingress-$$"
network="reolink-ftps-ingress-$$"

cleanup() {
    docker rm -f "${container}" >/dev/null 2>&1 || true
    docker network rm "${network}" >/dev/null 2>&1 || true
    docker run --rm --entrypoint /bin/chown \
        -v "${test_dir}:/cleanup" "${image}" \
        -R "$(id -u):$(id -g)" /cleanup >/dev/null 2>&1 || true
    rm -rf "${test_dir}"
}
trap cleanup EXIT

mkdir -p "${test_dir}/media/ReolinkSSD/reolink/front/day" \
    "${test_dir}/media/ReolinkSSD/reolink/viewer" \
    "${test_dir}/data" "${test_dir}/ssl" "${test_dir}/share"
printf '0123456789' >"${test_dir}/media/ReolinkSSD/reolink/front/day/clip.mp4"
cp tests/fixtures/options.json "${test_dir}/data/options.json"

docker network create --subnet 172.30.32.0/24 "${network}" >/dev/null
docker run -d --name "${container}" --network "${network}" --ip 172.30.32.10 \
    -v "${test_dir}/media:/media" \
    -v "${test_dir}/share:/share" \
    -v "${test_dir}/ssl:/ssl:ro" \
    -v "${test_dir}/data:/data" \
    "${image}" >/dev/null

for _ in {1..30}; do
    if docker logs "${container}" 2>&1 | grep -q "Recording browser ready"; then
        break
    fi
    sleep 1
done
docker logs "${container}" 2>&1 | grep -q "Recording browser ready"

docker run --rm --network "${network}" --ip 172.30.32.2 \
    --entrypoint python3 -v "${PWD}/tests:/tests:ro" "${image}" \
    /tests/integration_ingress.py http://172.30.32.10:8099

docker run --rm --network "${network}" --ip 172.30.32.3 \
    --entrypoint python3 -v "${PWD}/tests:/tests:ro" "${image}" \
    /tests/integration_ingress.py --expect-forbidden http://172.30.32.10:8099
