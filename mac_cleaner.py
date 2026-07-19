#!/usr/bin/env python3
"""Mac Cleaner — a safe, transparent disk-space cleaner for macOS.

Scans well-known cache and build-artifact locations, shows exactly what
was found with per-item sizes, and deletes only what you select.
Zero third-party dependencies: pure Python + Tkinter.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import queue

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    sys.exit(
        "Tkinter is not available in this Python.\n"
        "Install it with:  brew install python-tk\n"
        "or download the pre-built app from the GitHub releases page."
    )

HOME = os.path.expanduser("~")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG = "#0B0E14"
CARD = "#10141D"
CARD_SEL = "#16203A"
CARD_HOVER = "#141926"
BORDER = "#1C2230"
TEXT = "#E6EAF2"
DIM = "#8A93A6"
ACCENT = "#3B82F6"
GREEN = "#22C55E"
AMBER = "#F59E0B"
RED = "#EF4444"

BADGE_COLORS = {"SAFE": GREEN, "CAUTION": AMBER, "ADMIN": RED}

FONT = "Helvetica Neue"


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------
def _existing(*paths):
    return [p for p in paths if os.path.exists(p)]


def _children(directory):
    try:
        return [os.path.join(directory, c) for c in os.listdir(directory)]
    except OSError:
        return []


def _app_support(*names):
    out = []
    for name in names:
        out.append(os.path.join(HOME, "Library", "Application Support", name))
    return out


def paths_user_caches():
    return _children(os.path.join(HOME, "Library", "Caches")) + _children(
        os.path.join(HOME, ".cache")
    )


def paths_npm():
    return _existing(
        os.path.join(HOME, ".npm", "_cacache"),
        os.path.join(HOME, ".npm", "_npx"),
        os.path.join(HOME, ".pnpm-store"),
        os.path.join(HOME, "Library", "pnpm", "store"),
    )


def paths_gradle():
    return _existing(
        os.path.join(HOME, ".gradle", "caches"),
        os.path.join(HOME, ".gradle", "daemon"),
        os.path.join(HOME, ".gradle", "wrapper"),
    )


def paths_xcode():
    dev = os.path.join(HOME, "Library", "Developer", "Xcode")
    return _existing(
        os.path.join(dev, "DerivedData"),
        os.path.join(dev, "iOS DeviceSupport"),
    )


def paths_editor_caches():
    out = []
    for editor in ("Code", "Code - Insiders", "Cursor"):
        base = os.path.join(HOME, "Library", "Application Support", editor)
        out += _existing(
            os.path.join(base, "Cache"),
            os.path.join(base, "CachedData"),
            os.path.join(base, "Code Cache"),
            os.path.join(base, "GPUCache"),
        )
    return out


def paths_claude():
    base = os.path.join(HOME, "Library", "Application Support", "Claude")
    return _existing(
        os.path.join(base, "vm_bundles"),
        os.path.join(base, "Cache"),
        os.path.join(base, "Code Cache"),
        os.path.join(base, "GPUCache"),
    )


def paths_old_claude_cli():
    versions_dir = os.path.join(HOME, ".local", "share", "claude", "versions")
    if not os.path.isdir(versions_dir):
        return []

    def version_key(name):
        return [int(x) for x in re.findall(r"\d+", name)] or [0]

    versions = sorted(os.listdir(versions_dir), key=version_key)
    return [os.path.join(versions_dir, v) for v in versions[:-1]]


def paths_stremio():
    return _existing(*_app_support("stremio-server"))


def paths_expo():
    return _existing(
        os.path.join(HOME, ".expo", "expo-go"),
        os.path.join(HOME, ".expo", "android-apk-cache"),
    )


def paths_trash():
    return _children(os.path.join(HOME, ".Trash"))


def paths_avd_data():
    avd_root = os.path.join(HOME, ".android", "avd")
    if not os.path.isdir(avd_root):
        return []
    wipeable = (
        "userdata-qemu.img.qcow2",
        "userdata-qemu.img",
        "snapshots",
        "sdcard.img",
        "sdcard.img.qcow2",
        "cache.img",
        "cache.img.qcow2",
        "encryptionkey.img",
        "encryptionkey.img.qcow2",
    )
    out = []
    for entry in os.listdir(avd_root):
        if not entry.endswith(".avd"):
            continue
        for f in wipeable:
            out += _existing(os.path.join(avd_root, entry, f))
    return out


def paths_user_simulators():
    return _existing(os.path.join(HOME, "Library", "Developer", "CoreSimulator"))


def paths_system_simulators():
    return _existing("/Library/Developer/CoreSimulator")


CATEGORIES = [
    {
        "id": "caches",
        "icon": "🧹",
        "name": "App & system caches",
        "desc": "~/Library/Caches and ~/.cache — apps rebuild these automatically",
        "badge": "SAFE",
        "paths": paths_user_caches,
        "default": True,
    },
    {
        "id": "npm",
        "icon": "📦",
        "name": "JavaScript package caches",
        "desc": "npm, npx and pnpm download caches — restored on next install",
        "badge": "SAFE",
        "paths": paths_npm,
        "default": True,
    },
    {
        "id": "gradle",
        "icon": "🐘",
        "name": "Gradle build cache",
        "desc": "~/.gradle caches and daemons — rebuilt on next Android build",
        "badge": "SAFE",
        "paths": paths_gradle,
        "default": True,
    },
    {
        "id": "xcode",
        "icon": "🔨",
        "name": "Xcode derived data",
        "desc": "DerivedData and device support files — Xcode regenerates them",
        "badge": "SAFE",
        "paths": paths_xcode,
        "default": True,
    },
    {
        "id": "editors",
        "icon": "📝",
        "name": "Editor caches",
        "desc": "VS Code / Cursor cache folders — settings are not touched",
        "badge": "SAFE",
        "paths": paths_editor_caches,
        "default": True,
    },
    {
        "id": "claude",
        "icon": "🤖",
        "name": "Claude app caches",
        "desc": "VM bundles and caches — re-downloaded when needed",
        "badge": "SAFE",
        "paths": paths_claude,
        "default": True,
    },
    {
        "id": "claude_cli",
        "icon": "⌨️",
        "name": "Old Claude CLI versions",
        "desc": "Superseded CLI builds — the newest version is kept",
        "badge": "SAFE",
        "paths": paths_old_claude_cli,
        "default": True,
    },
    {
        "id": "stremio",
        "icon": "🎬",
        "name": "Stremio stream cache",
        "desc": "Cached video streams — safe to remove",
        "badge": "SAFE",
        "paths": paths_stremio,
        "default": True,
    },
    {
        "id": "expo",
        "icon": "📱",
        "name": "Expo caches",
        "desc": "Expo Go and APK caches — re-downloaded when needed",
        "badge": "SAFE",
        "paths": paths_expo,
        "default": True,
    },
    {
        "id": "trash",
        "icon": "🗑️",
        "name": "Trash",
        "desc": "Empties the Trash — files cannot be recovered afterwards",
        "badge": "CAUTION",
        "paths": paths_trash,
        "default": False,
    },
    {
        "id": "avd",
        "icon": "🧬",
        "name": "Android emulator data",
        "desc": "Wipes emulator storage — it boots fresh, apps inside are lost",
        "badge": "CAUTION",
        "paths": paths_avd_data,
        "default": False,
    },
    {
        "id": "sim_user",
        "icon": "🍏",
        "name": "iOS simulator devices",
        "desc": "Simulator devices and their data — recreated by Xcode",
        "badge": "CAUTION",
        "paths": paths_user_simulators,
        "default": False,
    },
    {
        "id": "sim_system",
        "icon": "⚙️",
        "name": "iOS simulator runtimes (system)",
        "desc": "Runtime disk images in /Library — needs admin password",
        "badge": "ADMIN",
        "paths": paths_system_simulators,
        "default": False,
    },
]


# ---------------------------------------------------------------------------
# Measurement / deletion helpers
# ---------------------------------------------------------------------------
def du_kb(paths):
    """Total on-disk KB for paths, staying on one filesystem (like du -skx)."""
    if not paths:
        return 0
    total = 0
    for chunk_start in range(0, len(paths), 50):
        chunk = paths[chunk_start : chunk_start + 50]
        try:
            out = subprocess.run(
                ["du", "-skx", *chunk],
                capture_output=True,
                text=True,
                timeout=600,
            ).stdout
            for line in out.splitlines():
                fields = line.split("\t", 1)
                if fields and fields[0].isdigit():
                    total += int(fields[0])
        except Exception:
            pass
    return total


def human(kb):
    if kb >= 1024 * 1024:
        return f"{kb / 1024 / 1024:.1f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.0f} MB"
    return f"{kb} KB"


def emulator_running():
    try:
        return (
            subprocess.run(
                ["pgrep", "-f", "qemu-system|emulator64"], capture_output=True
            ).returncode
            == 0
        )
    except Exception:
        return False


def delete_paths(paths):
    errors = 0
    for p in paths:
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
            else:
                shutil.rmtree(p, ignore_errors=False)
        except Exception:
            errors += 1
    return errors


def delete_admin_paths(paths):
    """Delete root-owned paths via a native macOS password prompt."""
    quoted = " ".join("'" + p.replace("'", "'\\''") + "'" for p in paths)
    script = f'do shell script "rm -rf {quoted}" with administrator privileges'
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    return result.returncode == 0


def brew_cleanup():
    if shutil.which("brew"):
        try:
            subprocess.run(
                ["brew", "cleanup", "-s", "--prune=all"],
                capture_output=True,
                timeout=300,
            )
        except Exception:
            pass


def free_disk_kb():
    return shutil.disk_usage(HOME).free // 1024


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class MacCleanerApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.rows = {}
        self.sizes = {}
        self.selected = {c["id"]: c["default"] for c in CATEGORIES}
        self.busy = False

        root.title("Mac Cleaner")
        root.geometry("880x680")
        root.minsize(760, 560)
        root.configure(bg=BG)
        try:  # dark native title bar where Tk supports it
            root.tk.call(
                "::tk::unsupported::MacWindowStyle", "appearance", root._w, "darkAqua"
            )
        except tk.TclError:
            pass

        self._build_header()
        self._build_toolbar()
        self._build_list()
        self._build_footer()

        root.after(80, self._poll_events)
        self.scan()

    # -- layout -------------------------------------------------------------
    def _build_header(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 6))

        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        tk.Label(
            left, text="Mac Cleaner", fg=TEXT, bg=BG, font=(FONT, 26, "bold")
        ).pack(anchor="w")
        tk.Label(
            left,
            text="Reclaim disk space — only regenerating caches, never your files",
            fg=DIM,
            bg=BG,
            font=(FONT, 12),
        ).pack(anchor="w")

        right = tk.Frame(header, bg=BG)
        right.pack(side="right")
        self.free_label = tk.Label(
            right, text="—", fg=GREEN, bg=BG, font=(FONT, 24, "bold")
        )
        self.free_label.pack(anchor="e")
        tk.Label(right, text="free on disk", fg=DIM, bg=BG, font=(FONT, 11)).pack(
            anchor="e"
        )

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=28, pady=(10, 8))

        self.clean_btn = self._button(
            bar, "Clean Selected", ACCENT, self.clean, padx=18
        )
        self.clean_btn.pack(side="right")
        self.rescan_btn = self._button(bar, "Rescan", CARD_SEL, self.scan)
        self.rescan_btn.pack(side="right", padx=(0, 10))

        self._button(bar, "Select safe", CARD, self.select_safe).pack(side="left")
        self._button(bar, "Select none", CARD, self.select_none).pack(
            side="left", padx=(10, 0)
        )

    def _button(self, parent, text, color, command, padx=14):
        btn = tk.Label(
            parent,
            text=text,
            fg=TEXT,
            bg=color,
            font=(FONT, 12, "bold"),
            padx=padx,
            pady=8,
            cursor="pointinghand",
        )
        btn.bind("<Button-1>", lambda _e: command())
        return btn

    def _build_list(self):
        outer = tk.Frame(self.root, bg=BORDER)
        outer.pack(fill="both", expand=True, padx=28, pady=(0, 4))
        inner_holder = tk.Frame(outer, bg=BG)
        inner_holder.pack(fill="both", expand=True, padx=1, pady=1)

        self.canvas = tk.Canvas(inner_holder, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(
            inner_holder, orient="vertical", command=self.canvas.yview
        )
        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.list_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.list_frame, anchor="nw"
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width),
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1 * int(e.delta), "units"),
        )

        for category in CATEGORIES:
            self._build_row(category)

    def _build_row(self, category):
        cid = category["id"]
        row = tk.Frame(self.list_frame, bg=CARD, pady=10)
        row.pack(fill="x", pady=(0, 6), padx=6)

        check = tk.Label(row, text="", width=2, bg=CARD, font=(FONT, 14, "bold"))
        check.pack(side="left", padx=(14, 4))

        icon = tk.Label(row, text=category["icon"], bg=CARD, font=(FONT, 16))
        icon.pack(side="left", padx=(0, 10))

        text_frame = tk.Frame(row, bg=CARD)
        text_frame.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(text_frame, bg=CARD)
        name_row.pack(anchor="w")
        name = tk.Label(
            name_row, text=category["name"], fg=TEXT, bg=CARD, font=(FONT, 13, "bold")
        )
        name.pack(side="left")
        badge = tk.Label(
            name_row,
            text=" " + category["badge"] + " ",
            fg=BG,
            bg=BADGE_COLORS[category["badge"]],
            font=(FONT, 9, "bold"),
        )
        badge.pack(side="left", padx=(8, 0))
        desc = tk.Label(
            text_frame, text=category["desc"], fg=DIM, bg=CARD, font=(FONT, 11)
        )
        desc.pack(anchor="w")

        size = tk.Label(
            row, text="…", fg=TEXT, bg=CARD, font=(FONT, 14, "bold"), width=8, anchor="e"
        )
        size.pack(side="right", padx=(4, 16))

        widgets = [row, check, icon, text_frame, name_row, name, desc, size]
        self.rows[cid] = {"widgets": widgets, "check": check, "size": size, "row": row}

        def on_click(_event, c=cid):
            if not self.busy:
                self.toggle(c)

        def on_enter(_event, c=cid):
            if not self.selected[c]:
                self._paint_row(c, CARD_HOVER)

        def on_leave(_event, c=cid):
            self._paint_row(c, CARD_SEL if self.selected[c] else CARD)

        for w in widgets + [badge]:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        self._refresh_row(cid)

    def _build_footer(self):
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=28, pady=(4, 18))
        self.status = tk.Label(
            footer, text="", fg=DIM, bg=BG, font=(FONT, 12), anchor="w"
        )
        self.status.pack(side="left")
        self.result = tk.Label(footer, text="", fg=GREEN, bg=BG, font=(FONT, 13, "bold"))
        self.result.pack(side="right")

    # -- row painting ---------------------------------------------------------
    def _paint_row(self, cid, color):
        for w in self.rows[cid]["widgets"]:
            try:
                w.configure(bg=color)
            except tk.TclError:
                pass

    def _refresh_row(self, cid):
        selected = self.selected[cid]
        self._paint_row(cid, CARD_SEL if selected else CARD)
        check = self.rows[cid]["check"]
        check.configure(text="✓" if selected else "○", fg=ACCENT if selected else DIM)

    # -- selection ------------------------------------------------------------
    def toggle(self, cid):
        self.selected[cid] = not self.selected[cid]
        self._refresh_row(cid)
        self._update_footer_hint()

    def select_safe(self):
        if self.busy:
            return
        for c in CATEGORIES:
            self.selected[c["id"]] = c["badge"] == "SAFE"
            self._refresh_row(c["id"])
        self._update_footer_hint()

    def select_none(self):
        if self.busy:
            return
        for c in CATEGORIES:
            self.selected[c["id"]] = False
            self._refresh_row(c["id"])
        self._update_footer_hint()

    def _update_footer_hint(self):
        total = sum(
            self.sizes.get(c["id"], 0) for c in CATEGORIES if self.selected[c["id"]]
        )
        if total:
            self.status.configure(text=f"Selected: {human(total)}")
        else:
            self.status.configure(text="")

    # -- scan -----------------------------------------------------------------
    def scan(self):
        if self.busy:
            return
        self.busy = True
        self.result.configure(text="")
        self.status.configure(text="Scanning…")
        for c in CATEGORIES:
            self.rows[c["id"]]["size"].configure(text="…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        for category in CATEGORIES:
            try:
                kb = du_kb(category["paths"]())
            except Exception:
                kb = 0
            self.events.put(("size", category["id"], kb))
        self.events.put(("scan_done", None, None))

    # -- clean ----------------------------------------------------------------
    def clean(self):
        if self.busy:
            return
        chosen = [c for c in CATEGORIES if self.selected[c["id"]]]
        chosen = [c for c in chosen if self.sizes.get(c["id"], 0) > 0]
        if not chosen:
            messagebox.showinfo("Mac Cleaner", "Nothing selected (or selection is empty).")
            return

        confirmed = []
        for category in chosen:
            if category["badge"] == "SAFE":
                confirmed.append(category)
                continue
            if category["id"] == "avd" and emulator_running():
                messagebox.showwarning(
                    "Mac Cleaner",
                    "The Android emulator is running.\nClose it first — skipping the wipe.",
                )
                continue
            size = human(self.sizes.get(category["id"], 0))
            if messagebox.askyesno(
                "Confirm — " + category["name"],
                f"{category['name']} ({size})\n\n{category['desc']}\n\nDelete?",
            ):
                confirmed.append(category)
        if not confirmed:
            return

        self.busy = True
        self.status.configure(text="Cleaning…")
        threading.Thread(
            target=self._clean_worker, args=(confirmed,), daemon=True
        ).start()

    def _clean_worker(self, chosen):
        before = free_disk_kb()
        for category in chosen:
            self.events.put(("progress", category["name"], None))
            try:
                paths = category["paths"]()
                if category["badge"] == "ADMIN":
                    if paths:
                        delete_admin_paths(paths)
                else:
                    delete_paths(paths)
                if category["id"] == "caches":
                    brew_cleanup()
                self.events.put(("size", category["id"], du_kb(category["paths"]())))
            except Exception:
                pass
        freed = max(0, free_disk_kb() - before)
        self.events.put(("clean_done", freed, None))

    # -- event pump ------------------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, a, b = self.events.get_nowait()
                if kind == "size":
                    self.sizes[a] = b
                    self.rows[a]["size"].configure(
                        text=human(b) if b else "—", fg=TEXT if b else DIM
                    )
                elif kind == "progress":
                    self.status.configure(text=f"Cleaning: {a}…")
                elif kind == "scan_done":
                    self.busy = False
                    self._update_footer_hint()
                    self.free_label.configure(text=human(free_disk_kb()))
                elif kind == "clean_done":
                    self.busy = False
                    self.free_label.configure(text=human(free_disk_kb()))
                    self.result.configure(text=f"✓ Freed {human(a)}")
                    self.status.configure(text="")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)


def main():
    root = tk.Tk()
    MacCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
