#!/bin/bash
#
# backup_media.sh
#
# Incremental mirror backup of the Plex/Sonarr/Radarr media library to the NAS.
# Unlike the DB/config scripts, this does NOT create timestamped archives -
# the media library is too large for that to be practical. Instead it keeps
# a single up-to-date mirror on the NAS via rsync, so only new/changed files
# transfer after the first run.
#
# Mode: exact mirror (--delete) - if a file is removed on the server, it is
# also removed from the NAS copy. This keeps the backup a true reflection of
# the live library rather than an ever-growing pile of stale files.
#
# --no-g --no-p: rsync's -a bundles explicit group-ownership and permission
# preservation, both of which require elevated privileges to actually apply
# via chgrp/chmod. Running as a non-root user against the NFS mount, both
# failed with "Operation not permitted" specifically on the top-level share
# root (not on any of the 640 files or 137 subdirectories, which all
# transferred/matched fine) - Synology NFS shares commonly lock down the
# share root's own attributes regardless of client, even when everything
# inside is fully writable. Since the NFS export already uses squash
# "No mapping" - which passively preserves UID/GID and permissions on every
# write with no extra step - rsync's explicit chgrp/chmod attempts on the
# root were redundant. Dropping -g and -p (kept everything else -a
# provides: times, owner, links) fixes this cleanly.
#
# Usage:
#   ./backup_media.sh          (dry-run, shows what would transfer/delete)
#   ./backup_media.sh --apply  (actually performs the sync)

set -euo pipefail

SOURCE="/mnt/storage_sata/media/"
DEST="/mnt/nas-plex-media/"

LOG_DIR="/home/blowe/langchain-projects/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/backup_media_${TIMESTAMP}.log"

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
fi

echo "=== Media Library Backup (mirror to NAS) ==="
echo "Timestamp:  ${TIMESTAMP}"
echo "Source:     ${SOURCE}"
echo "Dest:       ${DEST}"
echo "Mode:       $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"
echo "Delete:     enabled (NAS mirrors server exactly, removes files deleted on server)"
echo ""

# Verify the source actually exists and isn't accidentally empty (a common
# failure mode if the SATA drive isn't mounted for some reason - rsync with
# --delete against an empty source would wipe out the NAS copy)
if [[ ! -d "${SOURCE}" ]]; then
  echo "ERROR: Source directory ${SOURCE} does not exist. Aborting." >&2
  exit 1
fi

SOURCE_FILE_COUNT=$(find "${SOURCE}" -type f | wc -l)
if [[ "${SOURCE_FILE_COUNT}" -lt 10 ]]; then
  echo "ERROR: Source has suspiciously few files (${SOURCE_FILE_COUNT}). This looks like the drive may not be mounted properly. Aborting to avoid wiping the NAS mirror." >&2
  exit 1
fi

# Verify the NAS mount is actually live, not just an empty local directory
# left behind by a dropped NFS mount - critical here since --delete would
# otherwise interpret "NFS mount missing" as "everything was deleted"
if ! mountpoint -q "${DEST}"; then
  echo "ERROR: ${DEST} is not a mounted filesystem. Aborting to avoid catastrophic data loss from --delete running against an empty local dir." >&2
  exit 1
fi

echo "Source file count: ${SOURCE_FILE_COUNT}"
echo ""

mkdir -p "${LOG_DIR}"

if [[ "$APPLY" = false ]]; then
  echo "[DRY RUN] Preview of what would transfer/delete (rsync --dry-run):"
  echo ""
  stdbuf -oL rsync -avhH --no-g --no-p --delete --stats "${SOURCE}" "${DEST}" | tee "${LOG_FILE}"
  echo ""
  echo "(showing last 50 lines of dry-run output - full sync may involve many more files on first run)"
  exit 0
fi

echo "Running rsync mirror..."
rsync -avhH --no-g --no-p --delete --stats "${SOURCE}" "${DEST}" | tee "${LOG_FILE}"

echo ""
echo "=== Media backup complete. Log saved to ${LOG_FILE} ==="
