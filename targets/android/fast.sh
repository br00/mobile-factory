#!/usr/bin/env bash
# Fast checks for the Android app: lint, unit tests and a debug build.
# Exit 0 only when the branch is fit to review.
#
# mobile-factory runs this file from the factory repo (never from the app repo,
# so a branch can't change the checks it is judged by), with the job's worktree
# as the working directory. It sets:
#
#   MF_WORKTREE       the worktree being checked
#   MF_CACHE          a per-job scratch folder outside the worktree
#   MF_TARGET         "android"
#   MF_JOB            the job id
#   ...plus everything in mf.config.json targets.android.env:
#   MF_GRADLE_TASKS   space-separated Gradle tasks, e.g.
#                     "ktlintCheck detekt lintDebug testDebugUnitTest assembleDebug"
#
# Rules: non-interactive, deterministic, and never rewrite files (no
# ktlintFormat, no spotlessApply). Edit freely to match your app; this is the
# Android gate.
set -euo pipefail

: "${MF_GRADLE_TASKS:=lintDebug testDebugUnitTest assembleDebug}"
: "${MF_CACHE:=$(mktemp -d)}"

if [[ ! -x ./gradlew ]]; then
  echo "no executable ./gradlew in $PWD" >&2
  exit 1
fi

echo "== gradle $MF_GRADLE_TASKS"
# The shared ~/.gradle build cache speeds up every job; the project cache stays
# per job so two jobs never write the same .gradle folder.
# shellcheck disable=SC2086
./gradlew $MF_GRADLE_TASKS \
  --project-cache-dir "$MF_CACHE/gradle-project" \
  --console=plain \
  --stacktrace

echo "== ok"
