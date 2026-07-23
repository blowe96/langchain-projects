#!/bin/bash
# Daily job: copy new Immich mobile uploads into photos-import, then
# clean up the resulting mobile-vs-archive duplicates.

cd /home/blowe/langchain-projects || exit 1

echo "=== Run started: $(date) ===" >> daily_merge_log.txt
/home/blowe/.local/bin/uv run python3 merge_immich_uploads.py >> daily_merge_log.txt 2>&1

sleep 300

/home/blowe/.local/bin/uv run python3 resolve_duplicates.py --apply >> daily_merge_log.txt 2>&1
echo "=== Run finished: $(date) ===" >> daily_merge_log.txt
echo "" >> daily_merge_log.txt
