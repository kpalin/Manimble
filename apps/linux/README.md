# Manimble for Linux

The Linux desktop frontend is a GTK 4 application that uses Manimble's shared Python engine. It currently targets X11
and provides deck opening/creation, slide rendering and navigation, source editing, working-copy save, basic
presentation, and PowerPoint export.

## Install

Python 3.11 or later is required. Install GTK 4 and its introspection bindings from your distribution before using pip.
For Debian/Ubuntu:

```bash
sudo apt install gir1.2-gtk-4.0 libgirepository1.0-dev libcairo2-dev libpango1.0-dev pkg-config python3-dev build-essential
sudo apt install ffmpeg poppler-utils
python3 -m pip install .
```

PyGObject may require additional compiler or introspection development packages on other distributions.
Install a TeX Live distribution separately if a deck uses formulas or Beamer import/export.

With Conda, create an environment with GTK and PyGObject from conda-forge, then install Manimble from the repository:

```bash
conda env create -f apps/linux/environment.yml
conda activate manimble-linux
python -m pip install .
```

To build and install a Conda package instead, install rattler-build from conda-forge and use the Linux recipe:

```bash
conda create -n manimble-build -c conda-forge rattler-build
conda activate manimble-build
rattler-build build --recipe apps/linux/conda/recipe.yaml -c conda-forge --channel-priority disabled
conda create -n manimble-linux -c apps/linux/conda/output -c conda-forge --no-channel-priority manimble-linux
```

The recipe builds Manimble from this checkout and bundles the pinned Manim Slides Python package, which is not
published on conda-forge. Its other runtime dependencies, including GTK, Manim, and rendering libraries, are
resolved as Conda packages.

Launch the editor with:

```bash
manimble-linux
manimble-linux /path/to/deck
```

The Python environment used to launch the app must be able to import Manim. Set `MANIMBLE_PYTHON` to a different
interpreter when the desktop environment and Manim runtime use separate Python installations.

## Headless UI smoke test

Install `xvfb`, `xdotool`, and `x11-utils` (or ImageMagick for screenshots), then run:

```bash
env -u DISPLAY bash tests/linux_ui_smoke.sh
```

The smoke test launches the installed application with a two-slide fixture, edits and saves its source through the UI,
navigates slides using keyboard input, resizes the app window, and captures X11 screenshots. It starts Xvfb when no
display is active. The screenshot path is printed for visual inspection.

The shared engine and its JSON-lines protocol are documented in
[`../../engine/README.md`](../../engine/README.md) and [`../../docs/developers/protocol.md`](../../docs/developers/protocol.md).
