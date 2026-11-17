#!/usr/bin/env bash
set -euo pipefail

"$PYTHON" -m pip install "$SRC_DIR/manimble-source" \
  --no-deps --no-build-isolation --prefix "$PREFIX"
"$PYTHON" -m pip install "$SRC_DIR/manim-slides-source" \
  --no-deps --no-build-isolation --prefix "$PREFIX"
