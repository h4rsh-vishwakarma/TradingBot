#!/usr/bin/env bash
# Install Wallace as a git pre-push hook.
# Run once: bash scripts/install_wallace_hook.sh

HOOK=".git/hooks/pre-push"
REPO_ROOT="$(git rev-parse --show-toplevel)"

cat > "$HOOK" << 'HOOK_BODY'
#!/usr/bin/env bash
# Wallace pre-push hook — scans committed backtest CSVs before push.
# Blocks push only on CRITICAL flags (❌). Warnings (⚠️) pass through.

REPO="$(git rev-parse --show-toplevel)"

# Find any backtest CSV files being pushed
CSV_FILES=$(git diff --name-only HEAD~1..HEAD 2>/dev/null | grep -E '(mega_all_results|backtest.*results).*\.csv$' || true)

if [ -z "$CSV_FILES" ]; then
    exit 0
fi

echo "🔍 Wallace: scanning $CSV_FILES before push..."
CRITICAL=0
for f in $CSV_FILES; do
    if [ -f "$REPO/$f" ]; then
        output=$(cd "$REPO" && python3 scripts/wallace_check.py --csv "$f" --commission 0.06 2>&1)
        echo "$output"
        if echo "$output" | grep -q "critical"; then
            CRITICAL=1
        fi
    fi
done

if [ "$CRITICAL" -eq 1 ]; then
    echo ""
    echo "❌ WALLACE BLOCKED PUSH — critical governance violations in backtest results."
    echo "   Fix the flagged strategies or demote them before pushing."
    echo "   To bypass (not recommended): git push --no-verify"
    exit 1
fi

exit 0
HOOK_BODY

chmod +x "$HOOK"
echo "✅ Wallace pre-push hook installed at $HOOK"
