#!/bin/bash
# Snapshot and commit script for villa-adora-bot fixes
# Run from the repo directory

cd /Users/isakzvegelj/clawd/villa-adora-work || exit 1

# Create snapshot tag BEFORE changes
TAG="v$(date +%Y%m%d-%H%M%S)"
echo "Creating snapshot tag: $TAG"
git tag -a "$TAG" -m "snapshot before duplicate code cleanup and punctuation fixes"

# Stage all changes
git add -A
git status

echo ""
echo "Ready to commit. Run:"
echo "  git commit -m 'fix: remove duplicate non-English handling code, fix booking confirmation punctuation'"
echo "  git push origin main"
echo "  git push origin --tags"
