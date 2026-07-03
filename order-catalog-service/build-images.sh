#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${REGISTRY:-incidence.azurecr.io}"
TAG="${TAG:-1.0.0}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${ROOT}/app"

echo "==> Building ${REGISTRY}/order-catalog-service:${TAG}"
docker build -f "${APP_DIR}/Dockerfile" -t "${REGISTRY}/order-catalog-service:${TAG}" "${APP_DIR}"

echo ""
echo "Done. Push with:"
echo "  docker push ${REGISTRY}/order-catalog-service:${TAG}"
