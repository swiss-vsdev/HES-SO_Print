#!/usr/bin/env bash
# Build "HES-SO Print" for macOS (.app). For all platforms use .github/workflows/build.yml or scripts/build-*.sh
set -euo pipefail
exec "$(dirname "$0")/scripts/build-macos.sh"