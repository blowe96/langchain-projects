#!/bin/bash
exec > >(stdbuf -oL cat) 2>&1
#
# backup_configs.sh
#
# Nightly backup of mediastack + AdGuard container configs with dual-destination
# copy (NVMe + NAS) and rotation of old backups.
#
# Covers:
#   - Sonarr, Radarr, Prowlarr, qBittorrent configs (bind mounts under ~/mediastack)
#   - AdGuard Home conf + work (Docker named volumes, requires root to read)
#
# Must be run as root (or via sudo) because the AdGuard named volumes live
# under /var/lib/docker/volumes/ which is not readable by a normal user.
#
# Usage:
#   sudo ./backup_configs.sh          (dry-run, shows what would happen)
#   sudo ./backup_configs.sh --apply  (actually performs the backup)

set -euo pipefail

LOCAL_DEST="/mnt/storage_nvme/backups/configs"
NAS_DEST="/mnt/nas-configs-backup"

RETENTION_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="configs_${TIMESTAMP}.tar.gz"

# Source paths - update here if a service's config location ever changes
SOURCES=(
  "/home/blowe/mediastack/config/sonarr"
  "/home/blowe/mediastack/config/radarr"
  "/home/blowe/mediastack/config/prowlarr"
  "/home/blowe/mediastack/config/qbittorrent"
  "/var/lib/docker/volumes/adguard-home_adguard_conf/_data"
  "/var/lib/docker/volumes/adguard-home_adguard_work/_data"
)

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
fi

echo "=== Config Backup (Mediastack + AdGuard) ==="
echo "Timestamp:        ${TIMESTAMP}"
echo "Local dest:       ${LOCAL_DEST}/${FILENAME}"
echo "NAS dest:         ${NAS_DEST}/${FILENAME}"
echo "Retention:        ${RETENTION_DAYS} days"
echo "Mode:             $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"
echo ""

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: This script must be run as root (sudo) to read the AdGuard Docker volumes." >&2
  exit 1
fi

# Verify every source path actually exists before doing anything - a missing
# path usually means a service got renamed/moved and the script needs updating,
# not that it should silently back up a partial set.
MISSING=false
for src in "${SOURCES[@]}"; do
  if [[ ! -d "$src" ]]; then
    echo "ERROR: Expected config path not found: $src" >&2
    MISSING=true
  fi
done
if [[ "$MISSING" = true ]]; then
  echo "Aborting - one or more expected config paths are missing. Fix paths before proceeding." >&2
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
  echo "[DRY RUN] Would tar these paths into ${FILENAME}:"
  for src in "${SOURCES[@]}"; do
    echo "    - $src"
  done
  echo "[DRY RUN] Would copy to NAS: cp ${LOCAL_DEST}/${FILENAME} ${NAS_DEST}/${FILENAME}"
  echo "[DRY RUN] Would verify tar integrity of both copies"
  echo "[DRY RUN] Would delete backups older than ${RETENTION_DAYS} days in both locations"
  echo ""
  echo "Existing local backups:"
  ls -lh "${LOCAL_DEST}" 2>/dev/null || echo "  (none yet / directory doesn't exist)"
  echo "Existing NAS backups:"
  ls -lh "${NAS_DEST}" 2>/dev/null || echo "  (none yet / directory doesn't exist)"
  exit 0
fi

mkdir -p "${LOCAL_DEST}"

echo "Creating tarball..."
tar -czf "${LOCAL_DEST}/${FILENAME}" "${SOURCES[@]}"

if ! tar -tzf "${LOCAL_DEST}/${FILENAME}" >/dev/null 2>&1; then
  echo "ERROR: Local tarball failed integrity check. Aborting before NAS copy." >&2
  rm -f "${LOCAL_DEST}/${FILENAME}"
  exit 1
fi

ARCHIVE_SIZE=$(stat -c%s "${LOCAL_DEST}/${FILENAME}")
if [[ "${ARCHIVE_SIZE}" -lt 1024 ]]; then
  echo "ERROR: Archive is suspiciously small (${ARCHIVE_SIZE} bytes). Aborting." >&2
  rm -f "${LOCAL_DEST}/${FILENAME}"
  exit 1
fi

echo "Local backup OK (${ARCHIVE_SIZE} bytes). Copying to NAS..."

NAS_COPY_OK=false
for attempt in 1 2 3; do
  echo "NAS copy attempt ${attempt}/3..."
  if cp "${LOCAL_DEST}/${FILENAME}" "${NAS_DEST}/${FILENAME}" && tar -tzf "${NAS_DEST}/${FILENAME}" >/dev/null 2>&1; then
    NAS_COPY_OK=true
    break
  fi
  echo "NAS copy attempt ${attempt} failed or failed integrity check. Retrying in 30 seconds..." >&2
  rm -f "${NAS_DEST}/${FILENAME}"
  sleep 30
done

if [[ "$NAS_COPY_OK" != true ]]; then
  echo "ERROR: NAS copy failed after 3 attempts. Local backup is safe at ${LOCAL_DEST}/${FILENAME}, but NAS copy did not succeed." >&2
  exit 1
fi

echo "NAS copy verified OK."

echo "Rotating backups older than ${RETENTION_DAYS} days..."
find "${LOCAL_DEST}" -name "configs_*.tar.gz" -mtime "+${RETENTION_DAYS}" -print -delete
find "${NAS_DEST}" -name "configs_*.tar.gz" -mtime "+${RETENTION_DAYS}" -print -delete

echo ""
echo "=== Backup complete: ${FILENAME} ==="
