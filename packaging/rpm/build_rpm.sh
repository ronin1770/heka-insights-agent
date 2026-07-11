#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="heka-insights-agent"
SERVICE_NAME="heka-insights-agent.service"
ARCHITECTURE="x86_64"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <version> <packager>" >&2
  exit 1
fi

VERSION="$1"
PACKAGER="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RPM_ROOT="${REPO_ROOT}/build/rpmbuild"
SOURCES_DIR="${RPM_ROOT}/SOURCES"
SPECS_DIR="${RPM_ROOT}/SPECS"
PYINSTALLER_DIST_DIR="${REPO_ROOT}/dist"
OUTPUT_DIR="${REPO_ROOT}/dist"

rm -rf \
  "${RPM_ROOT}" \
  "${REPO_ROOT}/build/pyinstaller" \
  "${PYINSTALLER_DIST_DIR}/${PACKAGE_NAME}" \
  "${REPO_ROOT}/build/${PACKAGE_NAME}.spec"
mkdir -p \
  "${RPM_ROOT}/BUILD" \
  "${RPM_ROOT}/BUILDROOT" \
  "${RPM_ROOT}/RPMS" \
  "${RPM_ROOT}/SRPMS" \
  "${SOURCES_DIR}" \
  "${SPECS_DIR}" \
  "${OUTPUT_DIR}"

cd "${REPO_ROOT}"

pyinstaller \
  --onefile \
  --clean \
  --name "${PACKAGE_NAME}" \
  --paths "${REPO_ROOT}/src" \
  --workpath "${REPO_ROOT}/build/pyinstaller" \
  --specpath "${REPO_ROOT}/build" \
  "${REPO_ROOT}/src/main.py"

install -m 0755 \
  "${PYINSTALLER_DIST_DIR}/${PACKAGE_NAME}" \
  "${SOURCES_DIR}/${PACKAGE_NAME}"
install -m 0644 \
  "${SCRIPT_DIR}/${SERVICE_NAME}" \
  "${SOURCES_DIR}/${SERVICE_NAME}"
install -m 0644 \
  "${REPO_ROOT}/README.md" \
  "${SOURCES_DIR}/README.md"
install -m 0644 \
  "${REPO_ROOT}/LICENSE" \
  "${SOURCES_DIR}/LICENSE"
install -m 0644 \
  "${REPO_ROOT}/docs/configuration.md" \
  "${SOURCES_DIR}/configuration.md"
install -m 0644 \
  "${REPO_ROOT}/docs/release-packaging-rpm.md" \
  "${SOURCES_DIR}/release-packaging-rpm.md"
install -m 0644 \
  "${REPO_ROOT}/.env.example" \
  "${SOURCES_DIR}/env.example"
install -m 0644 \
  "${SCRIPT_DIR}/heka-insights-agent.spec" \
  "${SPECS_DIR}/heka-insights-agent.spec"

rpmbuild \
  --define "_topdir ${RPM_ROOT}" \
  --define "heka_version ${VERSION}" \
  --define "heka_packager ${PACKAGER}" \
  -bb "${SPECS_DIR}/heka-insights-agent.spec"

find "${RPM_ROOT}/RPMS" \
  -type f \
  -name "*.rpm" \
  -exec cp -f {} "${OUTPUT_DIR}/" \;

RPM_FILE="$(
  find "${OUTPUT_DIR}" \
    -maxdepth 1 \
    -type f \
    -name "${PACKAGE_NAME}-${VERSION}-*.${ARCHITECTURE}.rpm" \
    | head -1
)"

if [[ -z "${RPM_FILE}" ]]; then
  echo "RPM build completed, but the package was not found." >&2
  exit 1
fi

sha256sum "${RPM_FILE}" > "${RPM_FILE}.sha256"

echo "Built package: ${RPM_FILE}"
echo "Built checksum: ${RPM_FILE}.sha256"
