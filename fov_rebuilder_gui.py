#!/usr/bin/env python3
"""GUI launcher for 007 First Light custom FOV / camera rebuilds."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from rebuilder.core import RebuildError, RebuildResult, ensure_lz4, rebuild_and_install, remove_patches, resolve_runtime


APP_TITLE = "007 First Light FOV Rebuilder"
NEXUS_MOD_URL = "https://www.nexusmods.com/007firstlight/mods/15"

PRESETS: tuple[tuple[str, float, float, float], ...] = (
    ("Vanilla (remove patch)", 40.0, 0.0, 0.0),
    ("90 FOV", 90.0, 0.0, 0.0),
    ("90 FOV +10% distance +0.12 height (mod default)", 90.0, 10.0, 0.12),
    ("90 FOV +12% distance +0.15 height", 90.0, 12.0, 0.15),
    ("90 FOV -30% distance +0.12 height (closer)", 90.0, -30.0, 0.12),
    ("70 FOV +10% distance +0.12 height", 70.0, 10.0, 0.12),
    ("110 FOV +10% distance +0.12 height", 110.0, 10.0, 0.12),
)


class FovRebuilderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(640, 560)
        self.geometry("760x640")

        self.game_path = tk.StringVar()
        self.fov = tk.DoubleVar(value=90.0)
        self.distance = tk.DoubleVar(value=10.0)
        self.height = tk.DoubleVar(value=0.12)
        self.status = tk.StringVar(value="Ready.")
        self.busy = False

        self._build_ui()
        self._check_dependencies()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        intro = ttk.Label(
            root,
            text=(
                "Build and install custom camera patches for 007 First Light.\n"
                "Positive distance moves the camera farther from Bond; negative moves it closer."
            ),
            wraplength=700,
            justify=tk.LEFT,
        )
        intro.pack(anchor=tk.W, pady=(0, 10))

        path_frame = ttk.LabelFrame(root, text="Game folder", padding=10)
        path_frame.pack(fill=tk.X, pady=(0, 10))

        path_entry = ttk.Entry(path_frame, textvariable=self.game_path)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(path_frame, text="Browse...", command=self._browse_game).pack(side=tk.LEFT)

        settings = ttk.LabelFrame(root, text="Camera settings", padding=10)
        settings.pack(fill=tk.X, pady=(0, 10))

        self._add_spin_row(settings, "Target FOV", self.fov, 30.0, 120.0, 1.0, 0, "40 = vanilla label, 90 = Better Camera Main scale")
        self._add_spin_row(settings, "Distance (%)", self.distance, -60.0, 60.0, 1.0, 1, "+ = farther, - = closer")
        self._add_spin_row(settings, "Height", self.height, -0.75, 0.75, 0.01, 2, "Spherical camera framing height offset")

        preset_frame = ttk.LabelFrame(root, text="Presets", padding=10)
        preset_frame.pack(fill=tk.X, pady=(0, 10))
        preset_combo = ttk.Combobox(
            preset_frame,
            state="readonly",
            values=[name for name, _, _, _ in PRESETS],
            width=48,
        )
        preset_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        preset_combo.bind("<<ComboboxSelected>>", lambda event: self._apply_preset(preset_combo.get()))
        ttk.Button(preset_frame, text="Apply preset", command=lambda: self._apply_preset(preset_combo.get())).pack(side=tk.LEFT)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(0, 10))
        self.install_btn = ttk.Button(actions, text="Build && Install", command=self._install)
        self.install_btn.pack(side=tk.LEFT)
        self.remove_btn = ttk.Button(actions, text="Remove patch files", command=self._remove)
        self.remove_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Open Runtime folder", command=self._open_runtime).pack(side=tk.LEFT, padx=(8, 0))

        log_frame = ttk.LabelFrame(root, text="Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(log_frame, height=12, wrap=tk.WORD, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

        footer = ttk.Label(
            root,
            text=f"Based on Su4enka's Nexus mod: {NEXUS_MOD_URL}",
            wraplength=700,
            foreground="#555555",
        )
        footer.pack(anchor=tk.W, pady=(8, 0))

        status_bar = ttk.Label(root, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 4))
        status_bar.pack(fill=tk.X, pady=(8, 0))

    def _add_spin_row(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
        increment: float,
        precision: int,
        hint: str,
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text=label, width=16).pack(side=tk.LEFT)
        spin = ttk.Spinbox(
            row,
            from_=minimum,
            to=maximum,
            increment=increment,
            textvariable=variable,
            width=10,
            format=f"%.{precision}f",
        )
        spin.pack(side=tk.LEFT)
        ttk.Label(row, text=hint, wraplength=460, foreground="#555555").pack(side=tk.LEFT, padx=(10, 0))

    def _append_log(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _check_dependencies(self) -> None:
        try:
            ensure_lz4()
        except RebuildError as exc:
            self.status.set("Missing dependency.")
            messagebox.showerror(APP_TITLE, str(exc))

    def _browse_game(self) -> None:
        selected = filedialog.askdirectory(title="Select 007 First Light install or Runtime folder")
        if selected:
            self.game_path.set(selected)

    def _apply_preset(self, preset_name: str) -> None:
        for name, fov, distance, height in PRESETS:
            if name == preset_name:
                self.fov.set(fov)
                self.distance.set(distance)
                self.height.set(height)
                self._append_log(f"Applied preset: {name}")
                return

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.install_btn.configure(state=state)
        self.remove_btn.configure(state=state)

    def _install(self) -> None:
        if self.busy:
            return
        if not self.game_path.get().strip():
            messagebox.showwarning(APP_TITLE, "Select your game folder first.")
            return
        self._set_busy(True)
        self.status.set("Building patch...")
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self) -> None:
        try:
            ensure_lz4()
            result = rebuild_and_install(
                Path(self.game_path.get()),
                self.fov.get(),
                self.distance.get(),
                self.height.get(),
            )
        except RebuildError as exc:
            self.after(0, lambda: self._on_error(str(exc)))
            return
        except Exception as exc:  # pragma: no cover - safety net for GUI thread
            self.after(0, lambda: self._on_error(f"Unexpected error: {exc}"))
            return
        self.after(0, lambda: self._on_install_success(result))

    def _on_install_success(self, result: RebuildResult) -> None:
        self._set_busy(False)
        if result.removed_patch_files:
            self.status.set("Patch files removed.")
            self._append_log("All values are vanilla/default. Removed:")
            for name in result.removed_patch_files:
                self._append_log(f"  - {result.runtime / name}")
            messagebox.showinfo(APP_TITLE, "Vanilla values selected. Patch files removed.")
            return

        self.status.set("Installed successfully.")
        self._append_log("Built and installed:")
        self._append_log(f"  FOV={result.fov:g}, distance={result.distance_percent:g}%, height={result.height:g}")
        self._append_log(
            f"  Patched {result.patched_resources} resources / "
            f"{result.fov_values} FOV values / "
            f"{result.orbit_radii} orbit radii / "
            f"{result.height_offsets} height offsets"
        )
        for name in result.installed_files:
            self._append_log(f"  - {result.runtime / name}")
        messagebox.showinfo(APP_TITLE, "Camera patch installed. Launch the game to test.")

    def _remove(self) -> None:
        if self.busy:
            return
        if not self.game_path.get().strip():
            messagebox.showwarning(APP_TITLE, "Select your game folder first.")
            return
        try:
            runtime = resolve_runtime(Path(self.game_path.get()))
            removed = remove_patches(runtime)
        except RebuildError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if removed:
            self._append_log("Removed patch files:")
            for name in removed:
                self._append_log(f"  - {runtime / name}")
            messagebox.showinfo(APP_TITLE, "Removed patch204 files.")
        else:
            messagebox.showinfo(APP_TITLE, "No patch204 files were present.")

    def _open_runtime(self) -> None:
        if not self.game_path.get().strip():
            messagebox.showwarning(APP_TITLE, "Select your game folder first.")
            return
        try:
            runtime = resolve_runtime(Path(self.game_path.get()))
        except RebuildError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        import os

        os.startfile(runtime)

    def _on_error(self, message: str) -> None:
        self._set_busy(False)
        self.status.set("Failed.")
        self._append_log(message)
        messagebox.showerror(APP_TITLE, message)


def main() -> None:
    app = FovRebuilderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
