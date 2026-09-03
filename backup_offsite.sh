#!/bin/bash
#
# backup_offsite.sh
#
# Offsite backup of irreplaceable data to OneDrive via rclone, using the
# "onedrive-crypt" remote so all filenames and content are encrypted
# client-side before upload - OneDrive only ever sees opaque encrypted
# blobs, regardless of any photo-scanning/AI features Microsoft ships.
#
# Covers:
#   - photos-import (the irreplaceable photo/video archive) - uses rclone sync
#     with --backup-dir, so a locally deleted/replaced file is moved to a
#     dated "photos-import-deleted" folder offsite rather than being erased -
#     this is what makes the offsite copy safe against accidental deletion.
#     NOTE: --track-renames is NOT used here - it requires a shared hash
#     between source and destination to detect "same content, different
#     path," which is structurally impossible against a true client-side
#     encrypted remote (the whole point of encryption is that the ciphertext
#     bears no relationship to the plaintext). Practical effect: renaming or
#     moving files/folders locally will cause a re-upload under the new path,
#     with the old path preserved (not deleted) in the backup-dir folder.
#   - Immich DB dumps (already produced nightly by backup_immich_db.sh,
#     this script just copies the existing dump directory offsite - plain
#     copy is sufficient here since dump filenames are always unique
#     timestamps and never renamed)
#
# Rate limiting and reliability settings are applied to the photos sync:
#   --tpslimit 10 --transfers 2 --checkers 4
#     Avoids OneDrive/Graph API throttling. With ~87,000 individual files,
#     rclone's default concurrency (4 transfers/8 checkers) can trigger
#     Microsoft's per-second request throttling (HTTP 429 /
#     activityLimitReached), causing an escalating backoff that was observed
#     in practice as a transfer degrading to an ETA measured in weeks.
#   --onedrive-chunk-size 5Mi --timeout 60s --low-level-retries 20
#     Fixes a separate, genuine stuck-transfer issue observed during testing:
#     a single large file's upload chunk hung indefinitely (speed decaying
#     to a literal 0 B/s, xfr counter frozen, not a transient dip) rather
#     than timing out and retrying. Smaller chunks reduce how much work is
#     lost/retried when a stall happens, and --timeout forces rclone to
#     recognize a stalled connection and retry rather than waiting forever.
#     This matches rclone's own suggested fix from the error it raised:
#     "upload chunks may be taking too long - try reducing
#     --onedrive-chunk-size or decreasing --transfers".
# A brief, self-recovering dip in the live progress display (a few seconds
# of low throughput before returning to normal) is expected and not a
# problem. A genuinely stuck transfer shows the SAME xfr# and byte totals
# repeating across many consecutive stats lines with decaying speed toward
# 0 B/s - that is the pattern that indicates a real hang, not noise.
#
# Does NOT cover the media library or mediastack/AdGuard configs - both
# are replaceable/reconfigurable and not worth the offsite bandwidth/cost.
#
# Usage:
#   ./backup_offsite.sh          (dry-run, shows what would transfer)
#   ./backup_offsite.sh --apply  (actually performs the sync)
#   ./backup_offsite.sh --check  (verifies local vs offsite via hash comparison, no transfer)
#
# Uses a lock file (/tmp/backup_offsite.lock) to prevent overlapping runs -
# if a previous run (dry-run, apply, or check) is still in progress when
# this is invoked again (e.g. by cron firing before a slow run finished),
# the new invocation exits immediately instead of running concurrently.

set -euo pipefail

# Prevent overlapping runs - if a previous run is still going (e.g. a slow
# night) and the next cron trigger fires before it finishes, running two
# instances simultaneously would double the request load against OneDrive,
# which is exactly the kind of thing that triggers throttling. If the lock
# is already held, this run exits immediately rather than piling on.
LOCK_FILE="/tmp/backup_offsite.lock"
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "Another instance of backup_offsite.sh is already running. Exiting." >&2
  exit 1
fi

REMOTE="onedrive-crypt"

PHOTOS_SOURCE="/mnt/storage_sata/photos-import/"
PHOTOS_DEST="${REMOTE}:photos-import/"

DB_SOURCE="/mnt/storage_nvme/backups/immich-db/"
DB_DEST="${REMOTE}:immich-db/"

LOG_DIR="/home/blowe/langchain-projects/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Deleted/replaced photo files get moved here instead of destroyed, timestamped
# per run - this is what makes the offsite copy safe against accidental local
# deletion, since sync's normal behavior would otherwise erase them permanently
BACKUP_DIR="${REMOTE}:photos-import-deleted/${TIMESTAMP}/"
LOG_FILE="${LOG_DIR}/backup_offsite_${TIMESTAMP}.log"

APPLY=false
CHECK=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
elif [[ "${1:-}" == "--check" ]]; then
  CHECK=true
fi

echo "=== Offsite Backup (encrypted, to OneDrive via rclone crypt) ==="
echo "Timestamp:     ${TIMESTAMP}"
echo "Photos source: ${PHOTOS_SOURCE}"
echo "Photos dest:   ${PHOTOS_DEST}"
echo "DB source:     ${DB_SOURCE}"
echo "DB dest:       ${DB_DEST}"
echo "Mode:          $([ "$APPLY" = true ] && echo APPLY || ([ "$CHECK" = true ] && echo CHECK || echo DRY-RUN))"
echo ""

# Verify sources exist and aren't accidentally empty before syncing
if [[ ! -d "${PHOTOS_SOURCE}" ]]; then
  echo "ERROR: ${PHOTOS_SOURCE} does not exist. Aborting." >&2
  exit 1
fi
PHOTOS_FILE_COUNT=$(find "${PHOTOS_SOURCE}" -type f | wc -l)
if [[ "${PHOTOS_FILE_COUNT}" -lt 10 ]]; then
  echo "ERROR: Photos source has suspiciously few files (${PHOTOS_FILE_COUNT}). Possible mount issue. Aborting." >&2
  exit 1
fi

if [[ ! -d "${DB_SOURCE}" ]]; then
  echo "ERROR: ${DB_SOURCE} does not exist (has backup_immich_db.sh been run yet?). Aborting." >&2
  exit 1
fi

# Verify rclone can actually reach the remote before attempting a real sync or check
if [[ "$APPLY" = true || "$CHECK" = true ]]; then
  if ! rclone lsd "${REMOTE}:" >/dev/null 2>&1; then
    echo "ERROR: Cannot reach ${REMOTE} (OneDrive). Check network connection and rclone auth token. Aborting." >&2
    exit 1
  fi
fi

mkdir -p "${LOG_DIR}"

if [[ "$CHECK" = true ]]; then
  echo "Verifying photos-import against offsite copy (hash comparison, no transfer)..."
  rclone check "${PHOTOS_SOURCE}" "${PHOTOS_DEST}" -v 2>&1 | tee "${LOG_FILE}"
  echo ""
  echo "Verifying Immich DB dumps against offsite copy..."
  rclone check "${DB_SOURCE}" "${DB_DEST}" -v 2>&1 | tee -a "${LOG_FILE}"
  echo ""
  echo "=== Check complete. Any 'ERROR' or mismatch lines above indicate a real problem worth investigating. Log saved to ${LOG_FILE} ==="
  exit 0
fi

if [[ "$APPLY" = false ]]; then
  echo "[DRY RUN] Photos-import sync preview (deletions moved to ${BACKUP_DIR} rather than erased):"
  rclone sync "${PHOTOS_SOURCE}" "${PHOTOS_DEST}" --backup-dir="${BACKUP_DIR}" --tpslimit 10 --transfers 2 --checkers 4 --onedrive-chunk-size 5Mi --timeout 60s --low-level-retries 20 --dry-run -v 2>&1 | tail -30
  echo ""
  echo "[DRY RUN] Immich DB dumps copy preview:"
  rclone copy "${DB_SOURCE}" "${DB_DEST}" --tpslimit 10 --transfers 2 --onedrive-chunk-size 5Mi --timeout 60s --low-level-retries 20 --dry-run -v 2>&1 | tail -30
  echo ""
  echo "(showing last 30 lines of each dry-run - first run will involve many more files)"
  exit 0
fi

echo "Syncing photos-import to OneDrive (encrypted, deletions preserved in ${BACKUP_DIR})..."
rclone sync "${PHOTOS_SOURCE}" "${PHOTOS_DEST}" --backup-dir="${BACKUP_DIR}" --tpslimit 10 --transfers 2 --checkers 4 --onedrive-chunk-size 5Mi --timeout 60s --low-level-retries 20 --progress --stats-one-line --stats 30s 2>&1 | tee "${LOG_FILE}"

echo ""
echo "Copying Immich DB dumps to OneDrive (encrypted)..."
rclone copy "${DB_SOURCE}" "${DB_DEST}" --tpslimit 10 --transfers 2 --onedrive-chunk-size 5Mi --timeout 60s --low-level-retries 20 --progress --stats-one-line --stats 30s 2>&1 | tee -a "${LOG_FILE}"

echo ""
echo "=== Offsite backup complete. Log saved to ${LOG_FILE} ==="
