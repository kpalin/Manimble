# Copilot instructions for Manimble

## Repository overview

Manimble is a desktop slide editor for presentations built with Manim and Manim Slides. The codebase is split along practical boundaries rather than one monolithic app:

- `apps/macos/`: the Swift app, views, native macOS behaviors, and the app packaging/build scripts.
- `apps/linux/`: the GTK 4 frontend and Conda environment for X11.
- `engine/`: the platform-independent Python engine that owns deck state, render scheduling, AST edits, and export/import logic.
- `manimbler`: the command-line tool for validating, extracting, and converting portable `.manimble` packages.
- `tests/`: end-to-end checks for the package converter (`tests/test_manimbler.py`).
- `docs/`: the user guide published with MkDocs.
- `examples/`, `media/`: example decks and bundled assets.

The main architecture is: the macOS and Linux frontends talk to the Python engine (JSON-lines over stdin/stdout), and the engine orchestrates Manim rendering and slide/media packaging. The CLI tool (`manimbler`) reads and writes portable project archives rather than being the main editor runtime.

## Build and validation commands

### Local environment setup

```bash
./setup_python_env.sh
```

This installs the Python dependencies declared in `engine/requirements.txt` into the Manimble-managed environment.

### Full build from source

```bash
./install_manimble.sh
```

This is the repo’s full build path: it sets up Python dependencies, then builds the app and installs `manimbler` into `~/.local/bin`.

### App build only

```bash
apps/macos/build_app.sh
```

The CI workflow runs exactly this command in `.github/workflows/build.yml`.

### Linux frontend

```bash
conda env create -f apps/linux/environment.yml
conda activate manimble-linux
python -m pip install .
```

Or install the pip package in an environment with GTK 4/PyGObject system dependencies:

```bash
python -m pip install .
manimble-linux [path/to/deck]
```

### Docs build

```bash
pip install "mkdocs-material==9.6.23"
mkdocs build --strict --site-dir _site
```

This matches the documentation workflow in `.github/workflows/docs.yml`.

### Tests

```bash
python3 -m unittest tests.test_manimbler
```

To run a single test case:

```bash
python3 -m unittest tests.test_manimbler.ManimblerTests.test_check_and_info
```

Linux working-copy test:

```bash
python3 -m unittest tests.test_linux_workspace.WorkspaceTests.test_save_refuses_to_overwrite_a_concurrent_original_edit
```

Headless X11 UI flow (requires `xvfb`, `xdotool`, and `x11-utils`):

```bash
env -u DISPLAY bash tests/linux_ui_smoke.sh
```

The repo does not currently define a separate lint tool (no `ruff`, `flake8`, `black`, or `pre-commit` config was found in the root). The build and unittest suite are the main checks used in this project.

## Project-specific conventions

- The macOS frontend targets macOS 13+ and uses native Swift/AppKit. The Linux frontend targets GTK 4 on X11; keep platform UI code in its frontend rather than porting AppKit APIs directly.
- The Python engine is the source of truth for deck logic. If a bug touches rendering, edits, or export/import logic, check `engine/manimble/` before patching the app layer.
- Both frontends should keep engine requests asynchronous and use private deck working copies; the Linux client/workspace implementations are in `apps/linux/manimble_gtk/`.
- Decks are directories containing slide manifests and media; a deck may use `order.txt` to define the slide sequence. The portable `.manimble` package format expects a single manifest such as `manimble-project.json` and a relative `deckPath`.
- `manimbler` enforces strict archive validation and rejects unsafe paths, including traversal attempts such as `../`. Keep all file references relative to the project root and avoid introducing zip entries outside the deck directory.
- The app and the engine communicate over a JSON-lines protocol. If you change request/response fields, check the request dispatch and the protocol docs in `docs/developers/` rather than only patching one side of the call.
- Rendering output is organized around scene builds and slide manifests. The engine writes slide JSON files like `slides/<Scene>.json`, which reference media files and playback rates; keep the structure consistent with the existing package format.
- Use the repo’s existing build path when validating changes: if you touched the app, run the build script; if you changed the archive conversion path, use the end-to-end unittest file in `tests/test_manimbler.py`.

## Files and areas most likely to matter

- `engine/manimble/core.py`: deck state, render scheduling, edits, and presenter build logic.
- `engine/manimble/worker.py`: scene execution and frame generation.
- `engine/manimble/export.py` and `engine/manimble/importer.py`: import/export semantics.
- `manimbler`: portable archive inspection and conversion logic.
- `apps/macos/Sources/Manimble/`: Swift UI and document behaviors.
- `apps/linux/manimble_gtk/`: GTK UI, asynchronous JSON-lines client, and working-copy management.
- `docs/`: user-facing documentation and protocol documentation; CI builds it strictly.

When working in this repo, prefer changes that preserve the existing division between the native app, the Python engine, and the portable CLI package workflow.
