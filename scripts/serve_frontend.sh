#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
echo "Serving frontend at http://localhost:8000/frontend/"
python3 -m http.server 8000
