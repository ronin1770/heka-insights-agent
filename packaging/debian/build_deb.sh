#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="heka-insights-agent"
SERVICE_NAME="heka-insights-agent.service"
ARCHITECTURE="amd64"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <version> <maintainer>" >&2
  exit 1
fi

VERSION="$1"
MAINTAINER="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_ROOT="${REPO_ROOT}/build"
DIST_ROOT="${REPO_ROOT}/dist"
PYINSTALLER_DIST_DIR="${DIST_ROOT}"
OUTPUT_DIR="${DIST_ROOT}/ubuntu"
PACKAGE_ROOT="${BUILD_ROOT}/package-root"
PACKAGE_FILE="${OUTPUT_DIR}/${PACKAGE_NAME}_${VERSION}_${ARCHITECTURE}.deb"
DOC_DIR="${PACKAGE_ROOT}/usr/share/doc/${PACKAGE_NAME}"

rm -rf \
  "${BUILD_ROOT}" \
  "${PYINSTALLER_DIST_DIR}/${PACKAGE_NAME}" \
  "${PACKAGE_FILE}" \
  "${REPO_ROOT}/${PACKAGE_NAME}.spec"
mkdir -p "${BUILD_ROOT}" "${PYINSTALLER_DIST_DIR}" "${OUTPUT_DIR}" "${PACKAGE_ROOT}/DEBIAN" "${DOC_DIR}"

cd "${REPO_ROOT}"

pyinstaller \
  --onefile \
  --clean \
  --name "${PACKAGE_NAME}" \
  --paths "${REPO_ROOT}/src" \
  "${REPO_ROOT}/src/main.py"

install -d "${PACKAGE_ROOT}/usr/local/bin"
install -m 0755 "${PYINSTALLER_DIST_DIR}/${PACKAGE_NAME}" "${PACKAGE_ROOT}/usr/local/bin/${PACKAGE_NAME}"

install -d "${PACKAGE_ROOT}/lib/systemd/system"
install -m 0644 "${SCRIPT_DIR}/${SERVICE_NAME}" "${PACKAGE_ROOT}/lib/systemd/system/${SERVICE_NAME}"

install -d "${DOC_DIR}/examples"
install -m 0644 "${REPO_ROOT}/README.md" "${DOC_DIR}/README.md"
install -m 0644 "${REPO_ROOT}/LICENSE" "${DOC_DIR}/copyright"
install -m 0644 "${REPO_ROOT}/docs/configuration.md" "${DOC_DIR}/configuration.md"
install -m 0644 "${REPO_ROOT}/docs/release-packaging-debian.md" "${DOC_DIR}/release-packaging-debian.md"
install -m 0644 "${REPO_ROOT}/.env.example" "${DOC_DIR}/examples/.env.example"

install -m 0755 "${SCRIPT_DIR}/postinst" "${PACKAGE_ROOT}/DEBIAN/postinst"
install -m 0755 "${SCRIPT_DIR}/prerm" "${PACKAGE_ROOT}/DEBIAN/prerm"
install -m 0755 "${SCRIPT_DIR}/postrm" "${PACKAGE_ROOT}/DEBIAN/postrm"

cat > "${PACKAGE_ROOT}/DEBIAN/control" <<EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: ${ARCHITECTURE}
Maintainer: ${MAINTAINER}
Depends: adduser, systemd
Description: Heka Insights Agent standalone telemetry daemon
 Collects host telemetry and exports it through the configured backend.
 Includes an interactive setup flow and a systemd-managed packaged runtime.
EOF

dpkg-deb --build --root-owner-group "${PACKAGE_ROOT}" "${PACKAGE_FILE}"

echo "Built package: ${PACKAGE_FILE}"
