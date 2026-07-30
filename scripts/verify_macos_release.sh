#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <artifact.dmg> <expected-team-id>" >&2
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ $# -eq 2 ]] || {
  usage
  exit 2
}

[[ "$(uname -s)" == "Darwin" ]] || fail "macOS verification requires a macOS host"

artifact=$1
expected_team_id=$2
[[ -f "$artifact" ]] || fail "artifact not found: $artifact"

for tool in codesign hdiutil plutil shasum spctl xcrun; do
  command -v "$tool" >/dev/null 2>&1 || fail "required tool not found: $tool"
done

hdiutil verify "$artifact"
codesign --verify --strict "$artifact"
xcrun stapler validate "$artifact"

mount_dir=$(mktemp -d "${TMPDIR:-/tmp}/verify-speech-release.XXXXXX")
mounted=0
cleanup() {
  if [[ "$mounted" -eq 1 ]]; then
    hdiutil detach "$mount_dir" -quiet || hdiutil detach "$mount_dir" -force -quiet || true
  fi
  rmdir "$mount_dir" 2>/dev/null || true
}
trap cleanup EXIT

hdiutil attach "$artifact" -readonly -nobrowse -mountpoint "$mount_dir" -quiet
mounted=1
app_path=$(find "$mount_dir" -maxdepth 2 -type d -name 'Speech.app' -print -quit)
[[ -n "$app_path" ]] || fail "Speech.app not found in DMG"

codesign --verify --deep --strict "$app_path"
signature_details=$(codesign -d --verbose=4 "$app_path" 2>&1)
echo "$signature_details" | grep -q "flags=.*runtime" || fail "hardened runtime flag is missing"
team_id=$(echo "$signature_details" | awk -F= '/^TeamIdentifier=/{print $2; exit}')
[[ "$team_id" == "$expected_team_id" ]] || \
  fail "expected TeamIdentifier $expected_team_id, found ${team_id:-missing}"

entitlements_file=$(mktemp "${TMPDIR:-/tmp}/verify-speech-entitlements.XXXXXX")
codesign -d --entitlements :- "$app_path" > "$entitlements_file" 2>/dev/null
get_task_allow=$(plutil -extract com.apple.security.get-task-allow raw -o - "$entitlements_file" 2>/dev/null || echo false)
unlink "$entitlements_file"
[[ "$get_task_allow" != "true" ]] || fail "release application has get-task-allow enabled"

spctl --assess --type execute --verbose=4 "$app_path"
echo "TeamIdentifier: $team_id"
shasum -a 256 "$artifact"
echo "PASS: Speech macOS release trust checks completed"
