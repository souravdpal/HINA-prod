#!/usr/bin/env bash
set -euo pipefail

# ========= CONFIG =========
PARENT_MOUNT="/run/media/sourav/c66a6751-43e9-4dc0-8534-ef0403e815ed"
BASE_DIR="$PARENT_MOUNT/Mass music"
SLEEP_BETWEEN_DOWNLOADS=15
# ==========================

echo "=== yt-dlp batch downloader ==="

# ---- Check dependencies ----
for cmd in yt-dlp ffmpeg; do
    command -v "$cmd" >/dev/null || {
        echo "$cmd missing. Install with:"
        echo "sudo pacman -S yt-dlp ffmpeg"
        exit 1
    }
done

# ---- Check mount (CORRECT) ----
if ! mountpoint -q "$PARENT_MOUNT"; then
    echo "External drive not mounted at $PARENT_MOUNT"
    echo "Mount it first, then rerun."
    exit 1
fi

echo "Mount OK: $PARENT_MOUNT"

# ---- Ensure base dir ----
mkdir -p "$BASE_DIR"

# ---- Ask folder name ----
read -rp "Enter folder name: " FOLDER
TARGET_DIR="$BASE_DIR/$FOLDER"
mkdir -p "$TARGET_DIR"

echo "Download location: $TARGET_DIR"

# ---- Collect links ----
LINKS=()
echo "Paste YouTube links (type 'done' to start download):"

while true; do
    read -r URL
    [[ "$URL" == "done" ]] && break
    [[ -z "$URL" ]] && continue
    LINKS+=("$URL")
done

[[ ${#LINKS[@]} -eq 0 ]] && {
    echo "No links given."
    exit 0
}

# ---- yt-dlp options (stable MP4) ----
YTDLP_OPTS=(
    --yes-playlist
    --ignore-errors
    --continue
    --no-overwrites
    --no-part
    --merge-output-format mp4

    -f "bv*[ext=mp4]/bv*+ba[ext=m4a]/b[ext=mp4]"

    --embed-metadata
    --embed-thumbnail
    --convert-thumbnails jpg

    --sleep-interval 10
    --max-sleep-interval 30
    --limit-rate 2M

    -o "%(playlist_title|Uploads)s/%(playlist_index)03d - %(title)s.%(ext)s"
)

cd "$TARGET_DIR"

# ---- Download loop ----
i=0
for URL in "${LINKS[@]}"; do
    i=$((i+1))
    echo "[$i/${#LINKS[@]}] $URL"
    yt-dlp "${YTDLP_OPTS[@]}" "$URL"
    sleep "$SLEEP_BETWEEN_DOWNLOADS"
done

echo "=== Done. Files saved safely. ==="

