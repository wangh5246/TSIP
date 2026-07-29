#!/usr/bin/env bash
set -euo pipefail

readonly SERVICE_USER="waybill-receiver"
readonly SERVICE_GROUP="waybill-receiver"
readonly STATE_DIR="/var/lib/waybill-receiver"
readonly CONFIG_DIR="/etc/waybill"
readonly TLS_DIR="/etc/waybill/tls"
readonly UNIT_PATH="/etc/systemd/system/waybill-receiver-signer.service"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "error: run this installer as root" >&2
  exit 1
fi

for command_name in getent groupadd id install systemctl useradd; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "error: required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

for source_file in \
  "${SCRIPT_DIR}/waybill-receiver-signer.service" \
  "${SCRIPT_DIR}/waybill-receiver-signer.env.example"; do
  if [[ ! -f "${source_file}" || -L "${source_file}" ]]; then
    echo "error: missing or unsafe deployment input: ${source_file}" >&2
    exit 1
  fi
done

for target_dir in "${STATE_DIR}" "${CONFIG_DIR}" "${TLS_DIR}"; do
  if [[ -L "${target_dir}" ]]; then
    echo "error: refusing symlinked deployment directory: ${target_dir}" >&2
    exit 1
  fi
done

if ! getent group "${SERVICE_GROUP}" >/dev/null; then
  groupadd --system "${SERVICE_GROUP}"
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${SERVICE_GROUP}" \
    --home-dir /nonexistent \
    --no-create-home \
    --shell /usr/sbin/nologin \
    "${SERVICE_USER}"
else
  readonly EXISTING_GROUP="$(id -gn "${SERVICE_USER}")"
  readonly PASSWD_RECORD="$(getent passwd "${SERVICE_USER}")"
  readonly EXISTING_SHELL="${PASSWD_RECORD##*:}"
  if [[ "${EXISTING_GROUP}" != "${SERVICE_GROUP}" ]]; then
    echo "error: existing ${SERVICE_USER} user has an unexpected primary group" >&2
    exit 1
  fi
  if [[ "${EXISTING_SHELL}" != "/usr/sbin/nologin" && "${EXISTING_SHELL}" != "/bin/false" ]]; then
    echo "error: existing ${SERVICE_USER} user has an interactive shell" >&2
    exit 1
  fi
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0700 "${STATE_DIR}"
install -d -o root -g root -m 0755 "${CONFIG_DIR}"
install -d -o root -g root -m 0755 "${TLS_DIR}"
install -o root -g root -m 0644 \
  "${SCRIPT_DIR}/waybill-receiver-signer.service" "${UNIT_PATH}"
install -o root -g root -m 0644 \
  "${SCRIPT_DIR}/waybill-receiver-signer.env.example" \
  "${CONFIG_DIR}/receiver-signer.env.example"
systemctl daemon-reload

echo "Installed ${UNIT_PATH}."
echo "The service was deliberately not enabled or started."
echo "Next: install the frozen source and virtualenv, create the 0600 environment"
echo "file, initialize the receiver key as ${SERVICE_USER}, register its public key"
echo "with the Charger, configure the loopback TLS endpoint/CA, then enable the"
echo "service. See README_SERVER_DEPLOY.md."
