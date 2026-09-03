#!/bin/bash
#
# backup_secure_vault.sh
#
# Mirrors the Cryptomator-encrypted secure-vault to the NAS for disaster
# recovery in case the NVMe drive fails. The vault is already fully
# encrypted at rest (every filename and file's content) before this
# script ever touches it - this is a plain copy of already-encrypted
# data, no additional encryption layer needed here.
#
# Uses plain "copy" (never deletes on the NAS side) - if a file is
# genuinely removed from the vault, cleaning up the NAS copy should be
# a deliberate manual step, not something this script does automatically.
#
# Usage:
#   ./backup_secure_vault.sh          (dry-run, shows what would transfer)
#   ./backup_secure_vault.sh --apply  (actually performs the sync)
set -euo pipefail

SOURCE="/mnt/storage_nvme/secure-vault/"
DEST="/mnt/nas-secure-vault-backup/"
LOG_DIR="/home/blowe/langchain-projects/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/backup_secure_vault_${TIMESTAMP}.log"

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
fi

echo "=== Secure Vault Backup (already-encrypted Cryptomator vault -> NAS) ==="
echo "Timestamp: ${TIMESTAMP}"
echo "Source:    ${SOURCE}"
echo "Dest:      ${DEST}"
echo "Mode:      $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"
echo ""

if [[ ! -d "${SOURCE}" ]]; then
  echo "ERROR: ${SOURCE} does not exist. Aborting." >&2
  exit 1
fi

if ! mountpoint -q "${DEST}"; then
  echo "ERROR: ${DEST} is not a mounted filesystem. Aborting to avoid writing to local disk instead of the NAS." >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

if [[ "$APPLY" = false ]]; then
  echo "[DRY RUN] Sync preview:"
  rsync -rltvn --stats "${SOURCE}" "${DEST}" 2>&1 | tail -30
  exit 0
fi

echo "Syncing secure-vault to NAS..."
rsync -rltv --stats "${SOURCE}" "${DEST}" 2>&1 | tee "${LOG_FILE}"
echo ""
echo "=== Secure vault backup complete. Log saved to ${LOG_FILE} ==="
