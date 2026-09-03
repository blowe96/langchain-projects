#!/bin/bash
#
# backup_sensitive_docs.sh
#
# Encrypts and uploads sensitive documents to OneDrive via the "onedrive-crypt"
# rclone remote. Source is a Samba-shared inbox folder on the NVMe drive -
# drop files into \\192.168.68.200\NVME_Storage\sensitive-docs-inbox from
# Windows, and this script picks them up. Files sit briefly in plaintext on
# the local NVMe share until this script runs, then get encrypted before
# ever leaving the network.
#
# Uses plain "copy" (never deletes offsite) rather than "sync" - this inbox
# is expected to be low-volume and only grow over time, so simplicity and
# "nothing ever gets removed automatically" both make sense here. If a file
# needs to be removed from the offsite copy, that should be a deliberate
# manual rclone command, not something this script does automatically.
#
# Usage:
#   ./backup_sensitive_docs.sh          (dry-run, shows what would transfer)
#   ./backup_sensitive_docs.sh --apply  (actually performs the sync)
#   ./backup_sensitive_docs.sh --check  (verifies local vs offsite via hash comparison, no transfer)

set -euo pipefail

REMOTE="onedrive-crypt"

SOURCE="/mnt/storage_nvme/sensitive-docs-inbox/"
DEST="${REMOTE}:sensitive-docs/"

LOG_DIR="/home/blowe/langchain-projects/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/backup_sensitive_docs_${TIMESTAMP}.log"

APPLY=false
CHECK=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
elif [[ "${1:-}" == "--check" ]]; then
  CHECK=true
fi

echo "=== Sensitive Documents Backup (encrypted, to OneDrive via rclone crypt) ==="
echo "Timestamp: ${TIMESTAMP}"
echo "Source:    ${SOURCE}"
echo "Dest:      ${DEST}"
echo "Mode:      $([ "$APPLY" = true ] && echo APPLY || ([ "$CHECK" = true ] && echo CHECK || echo DRY-RUN))"
echo ""

if [[ ! -d "${SOURCE}" ]]; then
  echo "ERROR: ${SOURCE} does not exist. Aborting." >&2
  exit 1
fi

if [[ "$APPLY" = true || "$CHECK" = true ]]; then
  if ! rclone lsd "${REMOTE}:" >/dev/null 2>&1; then
    echo "ERROR: Cannot reach ${REMOTE} (OneDrive). Check network connection and rclone auth token. Aborting." >&2
    exit 1
  fi
fi

mkdir -p "${LOG_DIR}"

if [[ "$CHECK" = true ]]; then
  echo "Verifying sensitive-docs-inbox against offsite copy (hash comparison, no transfer)..."
  rclone check "${SOURCE}" "${DEST}" -v 2>&1 | tee "${LOG_FILE}"
  echo ""
  echo "=== Check complete. Any 'ERROR' or mismatch lines above indicate a real problem worth investigating. Log saved to ${LOG_FILE} ==="
  exit 0
fi

if [[ "$APPLY" = false ]]; then
  FILE_COUNT=$(find "${SOURCE}" -type f | wc -l)
  if [[ "${FILE_COUNT}" -eq 0 ]]; then
    echo "Inbox is currently empty - nothing to preview. Drop files into ${SOURCE} first."
    exit 0
  fi
  echo "[DRY RUN] Sync preview:"
  rclone copy "${SOURCE}" "${DEST}" --dry-run -v 2>&1 | tail -30
  exit 0
fi

echo "Uploading sensitive-docs-inbox to OneDrive (encrypted)..."
rclone copy "${SOURCE}" "${DEST}" --progress --stats-one-line --stats 30s 2>&1 | tee "${LOG_FILE}"

echo ""
echo "=== Sensitive documents backup complete. Log saved to ${LOG_FILE} ==="
