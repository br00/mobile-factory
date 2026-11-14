#!/usr/bin/env bash
# Fast checks for the iOS app: lint, then build and run the unit tests.
# Exit 0 only when the branch is fit to review.
#
# mobile-factory runs this file from the factory repo (never from the app repo,
# so a branch can't change the checks it is judged by), with the job's worktree
# as the working directory. It sets:
#
#   MF_WORKTREE      the worktree being checked
#   MF_CACHE         a per-job scratch folder outside the worktree
#   MF_TARGET        "ios"
#   MF_JOB           the job id
#   ...plus everything in mf.config.json targets.ios.env:
#   MF_SCHEME        the scheme to test (required)
#   MF_PROJECT       App.xcodeproj, or
#   MF_WORKSPACE     App.xcworkspace (wins when both are set)
#   MF_DESTINATION   e.g. "platform=iOS Simulator,name=iPhone 16"
#
# Rules: non-interactive, deterministic, and never rewrite files (no --fix,
# no autoformat). Edit freely to match your app; this is the iOS gate.
set -euo pipefail

: "${MF_SCHEME:?set targets.ios.env.MF_SCHEME in mf.config.json}"
: "${MF_DESTINATION:=platform=iOS Simulator,name=iPhone 16}"
: "${MF_CACHE:=$(mktemp -d)}"

container=()
if [[ -n "${MF_WORKSPACE:-}" ]]; then
  container=(-workspace "$MF_WORKSPACE")
elif [[ -n "${MF_PROJECT:-}" ]]; then
  container=(-project "$MF_PROJECT")
fi

if [[ -f .swiftlint.yml ]]; then
  if command -v swiftlint >/dev/null; then
    echo "== swiftlint"
    swiftlint lint --strict --quiet
  else
    echo "swiftlint isn't installed but the app has .swiftlint.yml" >&2
    exit 1
  fi
fi

if [[ -f .swift-format ]]; then
  echo "== swift-format"
  git ls-files -z '*.swift' | xargs -0 xcrun swift-format lint --strict
fi

echo "== xcodebuild test ($MF_SCHEME on $MF_DESTINATION)"
# ${container[@]+...} keeps bash 3.2 (macOS's /bin/bash) happy with an empty array under set -u.
xcodebuild test \
  ${container[@]+"${container[@]}"} \
  -scheme "$MF_SCHEME" \
  -destination "$MF_DESTINATION" \
  -derivedDataPath "$MF_CACHE/DerivedData" \
  -resultBundlePath "$MF_CACHE/results-$(date +%s).xcresult" \
  -quiet \
  CODE_SIGNING_ALLOWED=NO

echo "== ok"
