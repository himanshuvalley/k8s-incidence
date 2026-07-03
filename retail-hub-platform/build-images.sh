#!/usr/bin/env bash
set -euo pipefail
REGISTRY="${REGISTRY:-incidence.azurecr.io}"
TAG="${TAG:-1.0.0}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

SERVICES=(web gateway orders users inventory analytics payments)

for svc in "${SERVICES[@]}"; do
  echo "==> Building ${REGISTRY}/retail-hub-${svc}:${TAG}"
  docker build -f "${ROOT}/services/${svc}/Dockerfile" -t "${REGISTRY}/retail-hub-${svc}:${TAG}" "${ROOT}"
done

echo "Done. Push with:"
for svc in "${SERVICES[@]}"; do
  echo "  docker push ${REGISTRY}/retail-hub-${svc}:${TAG}"
done
