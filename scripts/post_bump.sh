#!/bin/bash
set -euo pipefail

# Update CITATION.cff date-released to today
sed -i "s/date-released:.*/date-released: $(date +%Y-%m-%d)/" CITATION.cff

# Clean up CHANGELOG.md via Claude CLI
cat CHANGELOG.md | claude -p 'review this and reword as needed no m-dashes. Output only the raw markdown, no code fences, no preamble.' > CHANGELOG.tmp && mv CHANGELOG.tmp CHANGELOG.md

# Amend the bump commit to include updated files, then re-tag
git add CITATION.cff CHANGELOG.md
git commit --amend --no-edit
git tag -f "$CZ_POST_CURRENT_TAG_VERSION"
