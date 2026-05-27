#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dave_dir="${ORBITLAB_DAVE_DIR:-"$repo_root/.orbitlab/external/DAVE"}"
dave_repo="${ORBITLAB_DAVE_REPO:-https://github.com/exoplanetvetting/DAVE.git}"
dave_commit="${ORBITLAB_DAVE_COMMIT:-aea19a30d987b214fb4c0cf01aa733f127c411b9}"

mkdir -p "$(dirname "$dave_dir")"

if [[ ! -d "$dave_dir/.git" ]]; then
  git clone "$dave_repo" "$dave_dir"
fi

if ! git -C "$dave_dir" rev-parse --verify "$dave_commit^{commit}" >/dev/null 2>&1; then
  git -C "$dave_dir" fetch --tags --force
fi
git -C "$dave_dir" checkout "$dave_commit"
make -C "$dave_dir/vetting" modshift

echo "$dave_dir/vetting/modshift"
