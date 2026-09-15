#!/usr/bin/env bash
# These scripts are copies of the youtube-timestamped-report skill, so the same code runs
# locally and on the runner. Re-copy them after changing the skill.
set -eu
SKILL="${1:-$HOME/.codex/skills/youtube-timestamped-report/scripts}"
cp "$SKILL"/*.py "$(dirname "$0")/"
echo "synced from $SKILL"
