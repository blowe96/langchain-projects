#!/bin/bash
#
# backup_immich_db.sh
#
# Nightly Immich Postgres backup with dual-destination copy (NVMe + NAS)
# and rotation of old backups.
#
# Usage:
#   ./backup_immich_db.sh          (dry-run, shows what would happen)
#   ./backup_immich_db.sh --apply  (actually performs the backup)

set -euo pipefail

CONTAINER="immich_postgres"
DB_NAME="immich"
DB_USER="postgres"

LOCAL_DEST="/mnt/storage_nvme/backups/immich-db"
NAS_DEST="/mnt/nas-immich-backups"

RETENTION_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="immich_db_${TIMESTAMP}.sql.gz"

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
fi

echo "=== Immich DB Backup ==="
echo "Timestamp:        ${TIMESTAMP}"
echo "Container:        ${CONTAINER}"
echo "Local dest:       ${LOCAL_DEST}/${FILENAME}"
echo "NAS dest:         ${NAS_DEST}/${FILENAME}"
echo "Retention:        ${RETENTION_DAYS} days"
echo "Mode:             $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"
echo ""

# Verify the container is actually running before attempting anything
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "ERROR: Container '${CONTAINER}' is not running. Aborting." >&2
  exit 1
fi

# Verify both destination mounts are actually mounted (not just empty local dirs
# from a dropped mount) before writing anything. Without this check, a failed/
# unmounted NVMe drive would look like an empty directory on the boot SSD, and
# the script would silently start writing "local" backups to the wrong drive.
if ! mountpoint -q "/mnt/storage_nvme"; then
  echo "ERROR: /mnt/storage_nvme is not a mounted filesystem. Aborting to avoid silently writing to the boot SSD instead of the NVMe drive." >&2
  exit 1
fi

if ! mountpoint -q "${NAS_DEST}"; then
  echo "ERROR: ${NAS_DEST} is not a mounted filesystem. Aborting to avoid writing to local disk instead of the NAS." >&2
  exit 1
fi

if [[ "$APPLY" = false ]]; then
  echo "[DRY RUN] Would create local dest dir: ${LOCAL_DEST}"
  echo "[DRY RUN] Would run: docker exec ${CONTAINER} pg_dump -U ${DB_USER} ${DB_NAME} | gzip > ${LOCAL_DEST}/${FILENAME}"
  echo "[DRY RUN] Would copy to NAS: cp ${LOCAL_DEST}/${FILENAME} ${NAS_DEST}/${FILENAME}"
  echo "[DRY RUN] Would verify gzip integrity of both copies"
  echo "[DRY RUN] Would delete backups older than ${RETENTION_DAYS} days in both locations"
  echo ""
  echo "Existing local backups:"
  ls -lh "${LOCAL_DEST}" 2>/dev/null || echo "  (none yet / directory doesn't exist)"
  echo "Existing NAS backups:"
  ls -lh "${NAS_DEST}" 2>/dev/null || echo "  (none yet / directory doesn't exist)"
  exit 0
fi

mkdir -p "${LOCAL_DEST}"

echo "Running pg_dump..."
docker exec "${CONTAINER}" pg_dump -U "${DB_USER}" "${DB_NAME}" | gzip > "${LOCAL_DEST}/${FILENAME}"

# Verify the dump isn't empty/corrupt before trusting it or copying it anywhere
if ! gzip -t "${LOCAL_DEST}/${FILENAME}" 2>/dev/null; then
  echo "ERROR: Local backup file failed gzip integrity check. Aborting before NAS copy." >&2
  rm -f "${LOCAL_DEST}/${FILENAME}"
  exit 1
fi

DUMP_SIZE=$(stat -c%s "${LOCAL_DEST}/${FILENAME}")
if [[ "${DUMP_SIZE}" -lt 1024 ]]; then
  echo "ERROR: Dump file is suspiciously small (${DUMP_SIZE} bytes). Likely a failed/empty dump. Aborting." >&2
  rm -f "${LOCAL_DEST}/${FILENAME}"
  exit 1
fi

echo "Local backup OK (${DUMP_SIZE} bytes). Copying to NAS..."
cp "${LOCAL_DEST}/${FILENAME}" "${NAS_DEST}/${FILENAME}"

if ! gzip -t "${NAS_DEST}/${FILENAME}" 2>/dev/null; then
  echo "ERROR: NAS copy failed integrity check after copy." >&2
  exit 1
fi

echo "NAS copy verified OK."

echo "Rotating backups older than ${RETENTION_DAYS} days..."
find "${LOCAL_DEST}" -name "immich_db_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print -delete
find "${NAS_DEST}" -name "immich_db_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print -delete

echo ""
echo "=== Backup complete: ${FILENAME} ==="
