#!/bin/bash
# Run the full daily pipeline locally.
# Usage: bash scripts/run_daily.sh

set -e

echo "=== OpenClaw Use Case Monitor — Manual Run ==="
echo "Date: $(date -u +%Y-%m-%d)"
echo ""

# Check required env vars
if [ -z "$MINIMAX_API_KEY" ]; then
    echo "WARNING: MINIMAX_API_KEY not set. LLM features will fail."
fi

echo "--- Step 1: Running scrapers ---"
python -m src.scrapers.run_all || echo "Some scrapers may have failed, continuing..."

echo ""
echo "--- Step 2: Processing pipeline ---"
python -m src.processors.run_pipeline

echo ""
echo "--- Step 3: Generating report ---"
python -m src.report_generator

echo ""
echo "=== Done ==="
echo "Report: outputs/daily-report/$(date -u +%Y-%m-%d).md"
echo "Latest: outputs/daily-report/latest.md"
