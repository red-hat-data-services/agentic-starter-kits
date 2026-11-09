#!/usr/bin/env bash
# Install the pinned Linux x86_64 release used by GitHub's ubuntu-latest runner.
set -euo pipefail

version="${1:?Usage: install_lychee.sh VERSION SHA256 DESTINATION}"
checksum="${2:?Expected SHA256 is required}"
destination="${3:?Installation directory is required}"
if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || ! "$checksum" =~ ^[a-f0-9]{64}$ ]]; then
  echo "Invalid lychee version or SHA256" >&2
  exit 1
fi

download_dir=$(mktemp -d)
trap 'rm -rf "$download_dir"' EXIT
archive="$download_dir/lychee.tar.gz"
archive_root="lychee-x86_64-unknown-linux-gnu"
url="https://github.com/lycheeverse/lychee/releases/download/lychee-${version}/${archive_root}.tar.gz"

# Retry transient transport/HTTP failures only. Permanent HTTP 404s fail immediately.
# -S retains the actual HTTP status, unlike the previous curl -sfLO invocation.
curl --fail --silent --show-error --location \
  --retry 3 --retry-delay 2 --retry-max-time 90 \
  --connect-timeout 10 --max-time 30 \
  --output "$archive" "$url"

python3 - "$archive" "$checksum" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as archive:
    actual = hashlib.file_digest(archive, "sha256").hexdigest()
if actual != sys.argv[2]:
    sys.exit(f"Lychee checksum mismatch: expected {sys.argv[2]}, got {actual}")
PY

tar -xzf "$archive" -C "$download_dir" "$archive_root/lychee"
mkdir -p "$destination"
install -m 755 "$download_dir/$archive_root/lychee" "$destination/lychee"
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$destination" >> "$GITHUB_PATH"
fi
echo "Installed lychee $version (SHA256 verified)"
