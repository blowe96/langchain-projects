"""
Auto-resolve Immich duplicate groups where the pattern is unambiguous.
"""

import argparse
import subprocess
from collections import defaultdict

DB_CONTAINER = "immich_postgres"
REPORT_PATH = "/mnt/storage_sata/duplicate_review_needed.txt"


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t", "-c", query],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("Fetching all active assets with a duplicate grouping...")
    query = """
        SELECT "duplicateId", id, "originalPath"
        FROM asset
        WHERE status = 'active' AND "duplicateId" IS NOT NULL;
    """
    raw = run_psql(query)

    groups = defaultdict(list)
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        dup_id, asset_id, path = parts
        groups[dup_id].append((asset_id, path))

    print(f"Total duplicate groups found: {len(groups)}")

    auto_resolve_trash_ids = []
    needs_review_groups = []

    for dup_id, members in groups.items():
        mobile = [(aid, p) for aid, p in members if p.startswith("/data/")]
        archive = [(aid, p) for aid, p in members if p.startswith("/usr/src/app/external/")]

        if mobile and archive:
            for aid, p in mobile:
                auto_resolve_trash_ids.append(aid)
        else:
            needs_review_groups.append((dup_id, members))

    print(f"\nAuto-resolvable (mobile duplicate of an archive file): {len(auto_resolve_trash_ids)} files to trash")
    print(f"Groups needing manual review: {len(needs_review_groups)}")

    with open(REPORT_PATH, "w") as f:
        f.write(f"DUPLICATE GROUPS NEEDING MANUAL REVIEW - {len(needs_review_groups)} groups\n")
        f.write("=" * 80 + "\n\n")
        for dup_id, members in needs_review_groups:
            f.write(f"Group {dup_id}:\n")
            for aid, p in members:
                f.write(f"    {p}\n")
            f.write("\n")
    print(f"Manual-review report written to: {REPORT_PATH}")

    if not args.apply:
        print("\n--- DRY RUN --- (no files were trashed)")
        print("First 10 mobile files that WOULD be trashed:")
        for aid in auto_resolve_trash_ids[:10]:
            print(f"  {aid}")
        print(f"\nRun again with --apply to actually trash these {len(auto_resolve_trash_ids)} mobile duplicates.")
        return

    print(f"\nApplying: trashing {len(auto_resolve_trash_ids)} mobile duplicate files...")
    batch_size = 500
    for i in range(0, len(auto_resolve_trash_ids), batch_size):
        batch = auto_resolve_trash_ids[i:i + batch_size]
        id_list = "', '".join(batch)
        update_query = f"""
            UPDATE asset
            SET status = 'trashed', "deletedAt" = now()
            WHERE id IN ('{id_list}');
        """
        run_psql(update_query)
        print(f"  ...trashed {min(i + batch_size, len(auto_resolve_trash_ids))}/{len(auto_resolve_trash_ids)}")

    print("\nDone. Mobile duplicates trashed, archive copies kept untouched.")
    print(f"Remember: {len(needs_review_groups)} groups still need your manual review - see {REPORT_PATH}")


if __name__ == "__main__":
    main()
