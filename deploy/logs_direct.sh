#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
touch logs/rag-agent.log
tail -n 200 -f logs/rag-agent.log

