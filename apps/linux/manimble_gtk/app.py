"""GTK desktop frontend for Manimble."""

from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

try:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk
except (ImportError, ValueError) as error:
    raise SystemExit(
        "Manimble needs GTK 4 and PyGObject. Install it with the documented Linux "
        "pip or Conda instructions."
    ) from error

from .engine_client import EngineClient
from .workspace import Workspace


_JOBS = ThreadPoolExecutor(max_workers=3, thread_name_prefix="manimble-ui")


class Presentation(Gtk.ApplicationWindow):
    def __init__(self, app, pages: list[str]):
        super().__init__(application=app, title="Manimble Presentation")
        self.pages = pages
        self.index = 0
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        if hasattr(self.picture, "set_content_fit"):
            self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.set_child(self.picture)
        self.fullscreen()
        self._show_page()

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _show_page(self):
        if self.pages:
            self.picture.set_filename(self.pages[self.index])
            self.set_title(f"Manimble Presentation — {self.index + 1}/{len(self.pages)}")

    def _on_key(self, _controller, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Escape,):
            self.close()
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_space, Gdk.KEY_Page_Down):
            self.index = min(self.index + 1, len(self.pages) - 1)
            self._show_page()
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self.index = max(self.index - 1, 0)
            self._show_page()
        else:
            return False
        return True


class ManimbleWindow(Gtk.ApplicationWindow):
    def __init__(self, app, initial_deck: str | None = None):
        super().__init__(application=app, title="Manimble")
        self.set_default_size(1120, 760)
        self.workspace: Workspace | None = None
        self.engine: EngineClient | None = None
        self.scene_name: str | None = None
        self.scene_source: dict | None = None
        self._loading_list = False
        self._busy = 0
        self._deck_dirty = False
        self._allow_close = False
        self._executor = _JOBS
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)
        root.append(self._make_header())

        horizontal = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        horizontal.set_wide_handle(True)
        horizontal.set_position(230)
        root.append(horizontal)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sidebar.set_margin_top(10)
        sidebar.set_margin_bottom(10)
        sidebar.set_margin_start(10)
        sidebar.set_margin_end(6)
        sidebar.append(Gtk.Label(label="Slides", xalign=0))
        self.scene_list = Gtk.ListBox()
        self.scene_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.scene_list.connect("row-selected", self._on_scene_selected)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.scene_list)
        list_scroll.set_vexpand(True)
        sidebar.append(list_scroll)
        horizontal.set_start_child(sidebar)
        horizontal.set_resize_start_child(False)

        vertical = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        vertical.set_wide_handle(True)
        vertical.set_position(500)
        vertical.set_hexpand(True)
        vertical.set_vexpand(True)
        horizontal.set_end_child(vertical)
        horizontal.set_resize_end_child(True)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        if hasattr(self.picture, "set_content_fit"):
            self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        canvas = Gtk.Box()
        canvas.set_hexpand(True)
        canvas.set_vexpand(True)
        canvas.set_margin_top(10)
        canvas.set_margin_bottom(10)
        canvas.set_margin_start(10)
        canvas.set_margin_end(10)
        canvas.append(self.picture)
        vertical.set_start_child(canvas)

        source_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        source_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        source_header.set_margin_start(10)
        source_header.set_margin_end(10)
        source_header.append(Gtk.Label(label="Scene source", xalign=0))
        reload_button = Gtk.Button(label="Discard draft")
        reload_button.connect("clicked", self._discard_source_draft)
        source_header.append(reload_button)
        apply_button = Gtk.Button(label="Apply source")
        apply_button.connect("clicked", self._apply_source)
        source_header.append(apply_button)
        source_box.append(source_header)
        self.source_buffer = Gtk.TextBuffer()
        self.source_buffer.connect("changed", self._source_buffer_changed)
        self.source_view = Gtk.TextView(buffer=self.source_buffer)
        self.source_view.set_monospace(True)
        self.source_view.set_wrap_mode(Gtk.WrapMode.NONE)
        source_scroll = Gtk.ScrolledWindow()
        source_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        source_scroll.set_child(self.source_view)
        source_scroll.set_min_content_height(120)
        source_scroll.set_vexpand(True)
        source_box.append(source_scroll)
        vertical.set_end_child(source_box)

        self.status = Gtk.Label(label="Open a Manimble deck to begin.", xalign=0)
        self.status.set_margin_top(5)
        self.status.set_margin_bottom(5)
        self.status.set_margin_start(10)
        root.append(self.status)

        if initial_deck:
            self.open_deck(Path(initial_deck))

    def _make_header(self):
        header = Gtk.HeaderBar()
        for label, callback, tooltip in (
            ("New", self._new_deck, "Create a deck"),
            ("Open", self._choose_deck, "Open a deck folder"),
            ("Save", self._save_deck, "Save changes to the original deck"),
            ("Present", self._present, "Present rendered slides"),
            ("Export PPTX", self._export_pptx, "Export to PowerPoint"),
        ):
            button = Gtk.Button(label=label)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            header.pack_start(button) if label in ("New", "Open", "Save") else header.pack_end(button)
        return header

    def _on_key(self, _controller, keyval, _keycode, state):
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval == Gdk.KEY_s:
                self._save_deck(None)
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self._apply_source(None)
                return True
        return False

    def _set_status(self, text: str):
        self.status.set_text(text)

    def _request(self, command: str, args: dict, done):
        if self.engine is None:
            self._set_status("Open a deck first.")
            return
        self._busy += 1
        self._set_status(f"{command.replace('_', ' ').capitalize()}…")
        future = self.engine.request(command, **args)

        def finish(result: Future):
            GLib.idle_add(self._complete_request, result, done)

        future.add_done_callback(finish)

    def _complete_request(self, future: Future, done):
        self._busy = max(0, self._busy - 1)
        try:
            result = future.result()
        except Exception as error:
            self._set_status(str(error))
            return GLib.SOURCE_REMOVE
        done(result)
        return GLib.SOURCE_REMOVE

    def _choose_deck(self, _button):
        chooser = Gtk.FileChooserNative.new(
            "Open Manimble deck", self, Gtk.FileChooserAction.SELECT_FOLDER, "Open", "Cancel"
        )
        chooser.connect("response", self._open_response)
        chooser.show()

    def _open_response(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            file = chooser.get_file()
            if file:
                self.open_deck(Path(file.get_path()))
        chooser.destroy()

    def _new_deck(self, _button):
        chooser = Gtk.FileChooserNative.new(
            "Choose a location for the new deck", self, Gtk.FileChooserAction.SELECT_FOLDER, "Create", "Cancel"
        )
        chooser.connect("response", self._new_response)
        chooser.show()

    def _new_response(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            parent = chooser.get_file()
            if parent:
                deck = Path(parent.get_path()) / "Manimble Deck"
                try:
                    deck.mkdir()
                    (deck / "order.txt").write_text("Welcome\n", encoding="utf-8")
                    (deck / "slides.py").write_text(
                        "from manim import *\nfrom manim_slides import Slide\n\n\n"
                        "class Welcome(Slide):\n"
                        "    def construct(self):\n"
                        "        self.add(Text('Welcome to Manimble'))\n",
                        encoding="utf-8",
                    )
                    (deck / "manim.cfg").write_text("[CLI]\n\n[logger]\n", encoding="utf-8")
                    self.open_deck(deck)
                except OSError as error:
                    self._set_status(f"Could not create deck: {error}")
        chooser.destroy()

    def open_deck(self, deck: Path):
        deck = deck.expanduser().resolve()
        if self.workspace and (self._deck_dirty or self._source_is_dirty()):
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="This deck has changes that have not been saved.",
            )
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Discard and open", Gtk.ResponseType.ACCEPT)
            dialog.connect("response", self._open_after_confirmation, deck)
            dialog.present()
            return
        self._prepare_open(deck)

    def _open_after_confirmation(self, dialog, response, deck: Path):
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            self._prepare_open(deck)

    def _prepare_open(self, deck: Path):
        self._set_status(f"Preparing a working copy of {deck.name}…")
        copy_future = self._executor.submit(Workspace, deck)

        def ready(future):
            GLib.idle_add(self._workspace_ready, future, deck)

        copy_future.add_done_callback(ready)

    def _workspace_ready(self, future: Future, original: Path):
        try:
            workspace = future.result()
        except Exception as error:
            self._set_status(f"Could not open deck: {error}")
            return GLib.SOURCE_REMOVE

        self._stop_engine(discard_workspace=True)
        self.workspace = workspace
        self.scene_name = None
        self.scene_source = None
        self._deck_dirty = False
        self.source_buffer.set_text("")
        self._refresh_title()
        try:
            self.engine = EngineClient(on_event=self._engine_event)
        except Exception as error:
            self._set_status(f"Could not start engine: {error}")
            return GLib.SOURCE_REMOVE
        self._request("open", {"deck": str(workspace.work), "cache": str(workspace.cache)}, self._opened)
        return GLib.SOURCE_REMOVE

    def _opened(self, result):
        if not result.get("ok"):
            self._set_status(result.get("error", "Could not open deck"))
            return
        self._load_state()

    def _load_state(self):
        self._request("state", {"current": self.scene_name or ""}, self._show_state)

    def _show_state(self, result):
        self._loading_list = True
        child = self.scene_list.get_first_child()
        while child:
            following = child.get_next_sibling()
            self.scene_list.remove(child)
            child = following
        scenes = result.get("scenes", [])
        for scene in scenes:
            row = Gtk.ListBoxRow()
            row.set_name(scene["name"])
            label = Gtk.Label(label=scene["name"], xalign=0)
            label.set_margin_top(5)
            label.set_margin_bottom(5)
            label.set_margin_start(8)
            label.set_margin_end(8)
            row.set_child(label)
            self.scene_list.append(row)
        selected = next((r for r in self._rows() if r.get_name() == self.scene_name), None)
        if selected is None:
            selected = self.scene_list.get_first_child()
        if selected:
            self.scene_list.select_row(selected)
            self.scene_list.grab_focus()
        self._loading_list = False
        if selected:
            self._select_scene(selected.get_name())
        else:
            self._set_status("No slides found in this deck.")

    def _rows(self):
        row = self.scene_list.get_first_child()
        while row:
            yield row
            row = row.get_next_sibling()

    def _on_scene_selected(self, _listbox, row):
        if row and not self._loading_list:
            self._select_scene(row.get_name())

    def _select_scene(self, name: str):
        if not name or not self.engine:
            return
        if self.scene_name and name != self.scene_name and self._source_is_dirty():
            self._set_status("Apply or discard the source draft before selecting another slide.")
            self._loading_list = True
            current = next((row for row in self._rows() if row.get_name() == self.scene_name), None)
            if current:
                self.scene_list.select_row(current)
            self._loading_list = False
            return
        self.scene_name = name
        self._request("scene", {"name": name}, self._show_scene)

    def _show_scene(self, result):
        if result.get("status") != "ready":
            self._set_status(result.get("error", f"Slide is {result.get('status', 'not ready')}"))
            return
        stops = result.get("stops", [])
        if stops:
            self.picture.set_filename(stops[-1]["png"])
        source = result.get("source") or {}
        self.scene_source = source
        self.source_buffer.set_text(source.get("text", ""))
        self._refresh_title()
        self._set_status(f"{result['name']} · {len(stops)} build(s)")

    def _apply_source(self, _button):
        if not self.engine or not self.scene_name or not self.scene_source:
            self._set_status("Select a slide before editing source.")
            return
        start, end = self.source_buffer.get_bounds()
        replacement = self.source_buffer.get_text(start, end, True)
        if replacement == self.scene_source["text"]:
            self._set_status("No source changes to apply.")
            return
        args = {
            "scene": self.scene_name,
            "file": self.scene_source["file"],
            "expected": self.scene_source["text"],
            "text": replacement,
        }
        self._request("edit_source", args, self._source_applied)

    def _source_is_dirty(self) -> bool:
        if not self.scene_source:
            return False
        start, end = self.source_buffer.get_bounds()
        return self.source_buffer.get_text(start, end, True) != self.scene_source.get("text")

    def _source_buffer_changed(self, _buffer):
        self._refresh_title()

    def _refresh_title(self):
        title = "Manimble"
        if self.workspace:
            title += f" — {self.workspace.original.name}"
        if self.scene_name:
            title += f" — {self.scene_name}"
        if self._deck_dirty or self._source_is_dirty():
            title += " *"
        self.set_title(title)

    def _discard_source_draft(self, _button):
        if self.scene_source:
            self.source_buffer.set_text(self.scene_source["text"])
            self._set_status("Source draft discarded.")

    def _source_applied(self, result):
        if not result.get("ok"):
            self._set_status(result.get("error", "Source edit was rejected"))
            return
        self._deck_dirty = True
        if self.scene_source:
            start, end = self.source_buffer.get_bounds()
            self.scene_source["text"] = self.source_buffer.get_text(start, end, True)
        self._refresh_title()
        self._set_status(result.get("message", "Source applied; rendering slide…"))
        self._load_state()

    def _save_deck(self, _button):
        if not self.workspace:
            self._set_status("Open a deck before saving.")
            return
        if self.scene_source:
            start, end = self.source_buffer.get_bounds()
            if self.source_buffer.get_text(start, end, True) != self.scene_source.get("text"):
                self._set_status("Apply source changes before saving the deck.")
                return
        self._set_status("Saving changes to the original deck…")
        future = self._executor.submit(self.workspace.save)
        future.add_done_callback(lambda result: GLib.idle_add(self._save_finished, result))

    def _save_finished(self, future: Future):
        try:
            changed = future.result()
        except Exception as error:
            self._set_status(f"Save failed: {error}")
        else:
            self._deck_dirty = False
            self._refresh_title()
            self._set_status("Deck saved." if changed else "No deck changes to save.")
        return GLib.SOURCE_REMOVE

    def _present(self, _button):
        self._request("pages", {"builds": False}, self._show_presentation)

    def _show_presentation(self, result):
        pages = result.get("pages", [])
        if not pages:
            self._set_status(result.get("error", "No rendered slides to present."))
            return
        player = Presentation(self.application, pages)
        player.present()

    def _export_pptx(self, _button):
        chooser = Gtk.FileChooserNative.new(
            "Export PowerPoint", self, Gtk.FileChooserAction.SAVE, "Export", "Cancel"
        )
        chooser.set_current_name("presentation.pptx")
        chooser.connect("response", self._export_response)
        chooser.show()

    def _export_response(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT and chooser.get_file():
            path = chooser.get_file().get_path()
            self._request("export", {"kind": "pptx", "path": path}, self._export_started)
        chooser.destroy()

    def _export_started(self, result):
        if not result.get("ok"):
            self._set_status(result.get("error", "Export could not start"))
        else:
            self._set_status("PowerPoint export started…")

    def _engine_event(self, message):
        GLib.idle_add(self._handle_engine_event, message)

    def _handle_engine_event(self, message):
        event = message.get("event")
        if event == "rendered" and message.get("name") == self.scene_name:
            self._select_scene(self.scene_name)
        elif event == "export":
            phase = message.get("phase", "working")
            if phase == "done":
                self._set_status(f"Exported {message.get('path', 'PowerPoint file')}")
            elif phase in ("error", "cancelled"):
                self._set_status(message.get("error", f"Export {phase}"))
            else:
                self._set_status(f"PowerPoint export: {phase}")
        elif event == "edit_failed":
            self._set_status(message.get("error", "The source edit could not be verified"))
        return GLib.SOURCE_REMOVE

    def _stop_engine(self, *, discard_workspace: bool):
        engine, workspace = self.engine, self.workspace
        self.engine = None
        if discard_workspace:
            self.workspace = None

        def finish():
            if engine:
                engine.close()
                try:
                    engine.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    engine.process.kill()
                    engine.process.wait()
            if discard_workspace and workspace:
                workspace.discard()

        _JOBS.submit(finish)

    def do_close_request(self):
        if (self._deck_dirty or self._source_is_dirty()) and not self._allow_close:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="This deck has changes that have not been saved.",
            )
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Discard and close", Gtk.ResponseType.ACCEPT)

            def close_after_confirmation(message_dialog, response):
                message_dialog.destroy()
                if response == Gtk.ResponseType.ACCEPT:
                    self._allow_close = True
                    self.close()

            dialog.connect("response", close_after_confirmation)
            dialog.present()
            return True
        self._stop_engine(discard_workspace=True)
        return False


class ManimbleApplication(Gtk.Application):
    def __init__(self, initial_deck: str | None):
        super().__init__(application_id="com.manimble.Linux", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.initial_deck = initial_deck
        self.window: ManimbleWindow | None = None

    def do_activate(self):
        if self.window is None:
            self.window = ManimbleWindow(self, self.initial_deck)
            self.initial_deck = None
        self.window.present()


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Manimble slide editor for Linux")
    parser.add_argument("deck", nargs="?", help="deck folder to open on launch")
    args = parser.parse_args(argv)
    app = ManimbleApplication(args.deck)
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
