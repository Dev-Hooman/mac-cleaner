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
import webbrowser

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    sys.exit(
        "Tkinter is not available in this Python.\n"
        "Install it with:  brew install python-tk\n"
        "or download the pre-built app from the GitHub releases page."
    )

__version__ = "1.2.0"

AUTHOR = "Abdul Rehman Sarfaraz"
AUTHOR_HANDLE = "Dev-Hooman"
URL_GITHUB = "https://github.com/Dev-Hooman"
URL_REPO = "https://github.com/Dev-Hooman/mac-cleaner"
URL_LINKEDIN = "https://www.linkedin.com/in/abdulrehman-sarfaraz/"

HOME = os.path.expanduser("~")
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG = "#0B0E14"
CARD = "#10141D"
CARD_SEL = "#131C2E"
CARD_HOVER = "#141926"
BORDER = "#1C2230"
TEXT = "#E6EAF2"
DIM = "#8A93A6"
FAINT = "#4B5566"
ACCENT = "#3B82F6"
GREEN = "#34D399"
AMBER = "#FBBF24"
RED = "#F87171"

BADGES = {
    "SAFE": {"fg": GREEN, "bg": "#0E2A1F"},
    "CAUTION": {"fg": AMBER, "bg": "#2E2410"},
    "ADMIN": {"fg": RED, "bg": "#331418"},
}

FONT = "Helvetica Neue"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


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
        os.path.join(HOME, ".bun", "install", "cache"),
        os.path.join(HOME, ".yarn", "berry", "cache"),
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
    return _existing(
        os.path.join(HOME, "Library", "Application Support", "stremio-server")
    )


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


# -- deep-scan discovery -----------------------------------------------------
def paths_node_modules():
    """Walk project folders (max depth 4) collecting node_modules dirs."""
    found = []
    skip_top = {
        "Library",
        "Applications",
        "Movies",
        "Music",
        "Pictures",
        "Public",
    }

    def walk(directory, depth):
        if depth > 4:
            return
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = entry.name
            if name.startswith("."):
                continue
            if depth == 0 and name in skip_top:
                continue
            if name == "node_modules":
                found.append(entry.path)
            else:
                walk(entry.path, depth + 1)

    walk(HOME, 0)
    return found


def paths_browser_caches():
    out = []
    bases = (
        os.path.join(HOME, "Library", "Application Support", "Google", "Chrome"),
        os.path.join(
            HOME, "Library", "Application Support", "BraveSoftware", "Brave-Browser"
        ),
        os.path.join(HOME, "Library", "Application Support", "Microsoft Edge"),
        os.path.join(HOME, "Library", "Application Support", "Chromium"),
    )
    for base in bases:
        if not os.path.isdir(base):
            continue
        for profile in _children(base):
            name = os.path.basename(profile)
            if name != "Default" and not name.startswith("Profile"):
                continue
            out += _existing(
                os.path.join(profile, "Cache"),
                os.path.join(profile, "Code Cache"),
                os.path.join(profile, "GPUCache"),
                os.path.join(profile, "Service Worker", "CacheStorage"),
                os.path.join(profile, "Service Worker", "ScriptCache"),
            )
    return out


def paths_xcode_archives():
    return _existing(os.path.join(HOME, "Library", "Developer", "Xcode", "Archives"))


def paths_device_backups():
    return _existing(
        os.path.join(HOME, "Library", "Application Support", "MobileSync", "Backup")
    )


CATEGORIES = [
    {
        "id": "caches",
        "name": "App & system caches",
        "desc": "~/Library/Caches and ~/.cache — apps rebuild these automatically",
        "badge": "SAFE",
        "paths": paths_user_caches,
        "default": True,
    },
    {
        "id": "npm",
        "name": "JavaScript package caches",
        "desc": "npm, pnpm, bun and yarn download caches — restored on next install",
        "badge": "SAFE",
        "paths": paths_npm,
        "default": True,
    },
    {
        "id": "gradle",
        "name": "Gradle build cache",
        "desc": "~/.gradle caches and daemons — rebuilt on next Android build",
        "badge": "SAFE",
        "paths": paths_gradle,
        "default": True,
    },
    {
        "id": "xcode",
        "name": "Xcode derived data",
        "desc": "DerivedData and device support files — Xcode regenerates them",
        "badge": "SAFE",
        "paths": paths_xcode,
        "default": True,
    },
    {
        "id": "editors",
        "name": "Editor caches",
        "desc": "VS Code / Cursor cache folders — settings are not touched",
        "badge": "SAFE",
        "paths": paths_editor_caches,
        "default": True,
    },
    {
        "id": "claude",
        "name": "Claude app caches",
        "desc": "VM bundles and caches — re-downloaded when needed",
        "badge": "SAFE",
        "paths": paths_claude,
        "default": True,
    },
    {
        "id": "claude_cli",
        "name": "Old Claude CLI versions",
        "desc": "Superseded CLI builds — the newest version is kept",
        "badge": "SAFE",
        "paths": paths_old_claude_cli,
        "default": True,
    },
    {
        "id": "stremio",
        "name": "Stremio stream cache",
        "desc": "Cached video streams — safe to remove",
        "badge": "SAFE",
        "paths": paths_stremio,
        "default": True,
    },
    {
        "id": "expo",
        "name": "Expo caches",
        "desc": "Expo Go and APK caches — re-downloaded when needed",
        "badge": "SAFE",
        "paths": paths_expo,
        "default": True,
    },
    {
        "id": "trash",
        "name": "Trash",
        "desc": "Empties the Trash — files cannot be recovered afterwards",
        "badge": "CAUTION",
        "paths": paths_trash,
        "default": False,
    },
    {
        "id": "avd",
        "name": "Android emulator data",
        "desc": "Wipes emulator storage — it boots fresh, apps inside are lost",
        "badge": "CAUTION",
        "paths": paths_avd_data,
        "default": False,
    },
    {
        "id": "sim_user",
        "name": "iOS simulator devices",
        "desc": "Simulator devices and their data — recreated by Xcode",
        "badge": "CAUTION",
        "paths": paths_user_simulators,
        "default": False,
    },
    {
        "id": "sim_system",
        "name": "iOS simulator runtimes (system)",
        "desc": "Runtime disk images in /Library — needs admin password",
        "badge": "ADMIN",
        "paths": paths_system_simulators,
        "default": False,
    },
    # -- deep scan only -----------------------------------------------------
    {
        "id": "node_modules",
        "name": "Project node_modules",
        "desc": "Dependency folders found in your projects — restore with npm install",
        "badge": "CAUTION",
        "paths": paths_node_modules,
        "default": False,
        "deep": True,
    },
    {
        "id": "browsers",
        "name": "Browser caches",
        "desc": "Chrome / Brave / Edge profile caches — quit the browser first",
        "badge": "SAFE",
        "paths": paths_browser_caches,
        "default": False,
        "deep": True,
    },
    {
        "id": "archives",
        "name": "Xcode archives",
        "desc": "Old app archives — needed to re-export past builds to App Store",
        "badge": "CAUTION",
        "paths": paths_xcode_archives,
        "default": False,
        "deep": True,
    },
    {
        "id": "backups",
        "name": "iPhone / iPad backups",
        "desc": "Local device backups — irreplaceable unless backed up elsewhere",
        "badge": "CAUTION",
        "paths": paths_device_backups,
        "default": False,
        "deep": True,
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


def _sh_quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def delete_admin_paths(paths):
    """Delete root-owned paths via a native macOS password prompt.

    Simulator runtimes are mounted as volumes — a plain rm -rf silently
    fails on the mountpoint, so any mounted volume beneath a target is
    detached first, inside the same privileged shell.

    Returns (ok, detail): detail is "cancelled" when the user dismissed
    the password prompt, otherwise stderr from the failed shell.
    """
    commands = []
    for p in paths:
        volumes_dir = os.path.join(p, "Volumes")
        if os.path.isdir(volumes_dir):
            commands.append(
                "for v in " + _sh_quote(volumes_dir) + "/*; do "
                '/usr/bin/hdiutil detach "$v" -force >/dev/null 2>&1 || true; done'
            )
        commands.append("rm -rf " + _sh_quote(p))
    shell = "; ".join(commands)
    script = (
        'do shell script "'
        + shell.replace("\\", "\\\\").replace('"', '\\"')
        + '" with administrator privileges'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    if "canceled" in result.stderr.lower() or "-128" in result.stderr:
        return False, "cancelled"
    return False, result.stderr.strip()[:200]


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
        self.active_cid = None
        self.spin_i = 0
        self.mode = "simple"
        self._scroll_accum = 0.0

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
        self._icon_image = None
        for icon_path in (
            os.path.join(APP_DIR, "assets", "icon.png"),
            os.path.join(APP_DIR, "icon.png"),
        ):
            if os.path.exists(icon_path):
                try:
                    self._icon_image = tk.PhotoImage(file=icon_path)
                    root.iconphoto(True, self._icon_image)
                except tk.TclError:
                    pass
                break

        self._build_header()
        self._build_toolbar()
        self._build_list()
        self._build_footer()

        root.after(80, self._poll_events)
        root.after(90, self._animate)
        self.scan()

    # -- category helpers ----------------------------------------------------
    def visible_categories(self):
        return [c for c in CATEGORIES if not c.get("deep") or self.mode == "deep"]

    # -- layout -------------------------------------------------------------
    def _build_header(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=30, pady=(24, 4))

        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        title_row = tk.Frame(left, bg=BG)
        title_row.pack(anchor="w")
        tk.Label(
            title_row, text="Mac Cleaner", fg=TEXT, bg=BG, font=(FONT, 25, "bold")
        ).pack(side="left")
        about = tk.Label(
            title_row,
            text="ⓘ",
            fg=FAINT,
            bg=BG,
            font=(FONT, 15),
            cursor="pointinghand",
        )
        about.pack(side="left", padx=(10, 0), pady=(6, 0))
        about.bind("<Button-1>", lambda _e: self.show_about())
        about.bind("<Enter>", lambda _e: about.configure(fg=ACCENT))
        about.bind("<Leave>", lambda _e: about.configure(fg=FAINT))
        tk.Label(
            left,
            text="Only regenerating caches and build artifacts — never your files.",
            fg=DIM,
            bg=BG,
            font=(FONT, 12),
        ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header, bg=BG)
        right.pack(side="right")
        self.free_label = tk.Label(
            right, text="—", fg=TEXT, bg=BG, font=(FONT, 22, "bold")
        )
        self.free_label.pack(anchor="e")
        tk.Label(
            right, text="FREE ON DISK", fg=FAINT, bg=BG, font=(FONT, 10, "bold")
        ).pack(anchor="e")

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=30, pady=(14, 10))

        # scan-mode switch
        pill = tk.Frame(bar, bg=CARD)
        pill.pack(side="left")
        self.mode_btns = {}
        for mode, label in (("simple", "Simple scan"), ("deep", "Deep scan")):
            btn = tk.Label(
                pill,
                text=label,
                font=(FONT, 11, "bold"),
                padx=13,
                pady=6,
                cursor="pointinghand",
            )
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda _e, m=mode: self.set_mode(m))
            self.mode_btns[mode] = btn
        self._style_mode_pill()

        self._text_button(bar, "Select safe", self.select_safe).pack(
            side="left", padx=(18, 0)
        )
        tk.Label(bar, text="·", fg=FAINT, bg=BG, font=(FONT, 12)).pack(
            side="left", padx=6
        )
        self._text_button(bar, "Select none", self.select_none).pack(side="left")

        self.clean_btn = self._button(bar, "Clean Selected", self.clean, primary=True)
        self.clean_btn.pack(side="right")
        self.rescan_btn = self._button(bar, "Rescan", self.scan)
        self.rescan_btn.pack(side="right", padx=(0, 10))

    def _style_mode_pill(self):
        for mode, btn in self.mode_btns.items():
            if mode == self.mode:
                btn.configure(bg=ACCENT, fg="#FFFFFF")
            else:
                btn.configure(bg=CARD, fg=DIM)

    def set_mode(self, mode):
        if self.busy or mode == self.mode:
            return
        self.mode = mode
        self._style_mode_pill()
        for category in CATEGORIES:
            if not category.get("deep"):
                continue
            cid = category["id"]
            if mode == "deep":
                self.rows[cid]["row"].pack(fill="x", pady=(0, 5), padx=6)
            else:
                self.selected[cid] = False
                self._refresh_row(cid)
                self.rows[cid]["row"].pack_forget()
        self.scan()

    def _button(self, parent, text, command, primary=False):
        btn = tk.Label(
            parent,
            text=text,
            fg="#FFFFFF" if primary else TEXT,
            bg=ACCENT if primary else CARD_SEL,
            font=(FONT, 12, "bold"),
            padx=18 if primary else 14,
            pady=8,
            cursor="pointinghand",
        )
        btn._base_bg = ACCENT if primary else CARD_SEL
        btn.bind("<Button-1>", lambda _e: command())
        return btn

    def _text_button(self, parent, text, command):
        btn = tk.Label(
            parent, text=text, fg=DIM, bg=BG, font=(FONT, 12), cursor="pointinghand"
        )
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(fg=TEXT))
        btn.bind("<Leave>", lambda _e: btn.configure(fg=DIM))
        return btn

    def _build_list(self):
        outer = tk.Frame(self.root, bg=BORDER)
        outer.pack(fill="both", expand=True, padx=30, pady=(0, 6))
        inner_holder = tk.Frame(outer, bg=BG)
        inner_holder.pack(fill="both", expand=True, padx=1, pady=1)

        self.canvas = tk.Canvas(
            inner_holder, bg=BG, highlightthickness=0, yscrollincrement=8
        )
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

        # mouse wheels report notches; trackpads (Tk 8.7+) report precise
        # pixel deltas through the separate TouchpadScroll event
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        try:
            self.canvas.bind_all("<TouchpadScroll>", self._on_touchpad)
        except tk.TclError:
            pass

        for category in CATEGORIES:
            self._build_row(category)
            if category.get("deep"):
                self.rows[category["id"]]["row"].pack_forget()

    def _on_wheel(self, event):
        delta = event.delta
        if abs(delta) >= 120:
            delta //= 120
        self.canvas.yview_scroll(-delta * 3, "units")

    def _on_touchpad(self, event):
        try:
            _dx, dy = self.root.tk.call("tk::PreciseScrollDeltas", event.delta)
            dy = float(dy)
        except (tk.TclError, ValueError):
            dy = float(event.delta)
        if not dy:
            return
        self._scroll_accum += dy
        steps = int(self._scroll_accum / 8)
        if steps:
            self._scroll_accum -= steps * 8
            self.canvas.yview_scroll(-steps, "units")

    def _build_row(self, category):
        cid = category["id"]
        row = tk.Frame(self.list_frame, bg=CARD, pady=11)
        row.pack(fill="x", pady=(0, 5), padx=6)

        check = tk.Label(
            row,
            text="",
            width=2,
            bg="#1A2130",
            fg="#FFFFFF",
            font=(FONT, 11, "bold"),
        )
        check.pack(side="left", padx=(16, 14))

        text_frame = tk.Frame(row, bg=CARD)
        text_frame.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(text_frame, bg=CARD)
        name_row.pack(anchor="w")
        name = tk.Label(
            name_row, text=category["name"], fg=TEXT, bg=CARD, font=(FONT, 13, "bold")
        )
        name.pack(side="left")
        badge_style = BADGES[category["badge"]]
        badge = tk.Label(
            name_row,
            text=category["badge"],
            fg=badge_style["fg"],
            bg=badge_style["bg"],
            font=(FONT, 9, "bold"),
            padx=6,
            pady=1,
        )
        badge.pack(side="left", padx=(10, 0))
        state = tk.Label(name_row, text="", fg=GREEN, bg=CARD, font=(FONT, 10, "bold"))
        state.pack(side="left", padx=(10, 0))
        desc = tk.Label(
            text_frame, text=category["desc"], fg=DIM, bg=CARD, font=(FONT, 11)
        )
        desc.pack(anchor="w", pady=(1, 0))

        size = tk.Label(
            row,
            text="…",
            fg=TEXT,
            bg=CARD,
            font=(FONT, 13, "bold"),
            width=9,
            anchor="e",
        )
        size.pack(side="right", padx=(4, 18))

        widgets = [row, text_frame, name_row, name, desc, size, state]
        self.rows[cid] = {
            "widgets": widgets,
            "check": check,
            "size": size,
            "state": state,
            "row": row,
        }

        def on_click(_event, c=cid):
            if not self.busy:
                self.toggle(c)

        def on_enter(_event, c=cid):
            if not self.busy and not self.selected[c]:
                self._paint_row(c, CARD_HOVER)

        def on_leave(_event, c=cid):
            self._paint_row(c, CARD_SEL if self.selected[c] else CARD)

        for w in widgets + [badge, check]:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        self._refresh_row(cid)

    def _build_footer(self):
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=30, pady=(4, 20))
        self.status = tk.Label(
            footer, text="", fg=DIM, bg=BG, font=(FONT, 12), anchor="w"
        )
        self.status.pack(side="left")
        self.result = tk.Label(
            footer, text="", fg=GREEN, bg=BG, font=(FONT, 13, "bold")
        )
        self.result.pack(side="right")

    # -- about dialog ---------------------------------------------------------
    def show_about(self):
        win = tk.Toplevel(self.root)
        win.title("About Mac Cleaner")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        try:
            win.tk.call(
                "::tk::unsupported::MacWindowStyle", "appearance", win._w, "darkAqua"
            )
        except tk.TclError:
            pass

        body = tk.Frame(win, bg=BG, padx=44, pady=30)
        body.pack()

        if self._icon_image is not None:
            factor = max(1, self._icon_image.width() // 110)
            self._about_icon = self._icon_image.subsample(factor, factor)
            tk.Label(body, image=self._about_icon, bg=BG).pack()

        tk.Label(
            body, text="Mac Cleaner", fg=TEXT, bg=BG, font=(FONT, 20, "bold")
        ).pack(pady=(8, 0))
        tk.Label(
            body, text=f"Version {__version__}", fg=FAINT, bg=BG, font=(FONT, 11)
        ).pack()

        tk.Frame(body, bg=BORDER, height=1, width=240).pack(pady=16)

        tk.Label(
            body, text=f"Developed by {AUTHOR}", fg=TEXT, bg=BG, font=(FONT, 13)
        ).pack()
        tk.Label(
            body, text=f"@{AUTHOR_HANDLE}", fg=DIM, bg=BG, font=(FONT, 11)
        ).pack(pady=(1, 12))

        for label, url in (
            ("GitHub profile", URL_GITHUB),
            ("LinkedIn", URL_LINKEDIN),
            ("Source code & releases", URL_REPO),
        ):
            link = tk.Label(
                body,
                text=label,
                fg=ACCENT,
                bg=BG,
                font=(FONT, 12),
                cursor="pointinghand",
            )
            link.pack(pady=2)
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
            link.bind("<Enter>", lambda _e, w=link: w.configure(fg="#7DB2FF"))
            link.bind("<Leave>", lambda _e, w=link: w.configure(fg=ACCENT))

        tk.Label(
            body,
            text="MIT License — free & open source",
            fg=FAINT,
            bg=BG,
            font=(FONT, 10),
        ).pack(pady=(16, 0))

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 120
        win.geometry(f"+{x}+{y}")

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
        if selected:
            check.configure(text="✓", bg=ACCENT, fg="#FFFFFF")
        else:
            check.configure(text="", bg="#1A2130")

    def _set_row_state(self, cid, text, color):
        self.rows[cid]["state"].configure(text=text, fg=color)

    # -- selection ------------------------------------------------------------
    def toggle(self, cid):
        self.selected[cid] = not self.selected[cid]
        self._refresh_row(cid)
        self._update_footer_hint()

    def select_safe(self):
        if self.busy:
            return
        for c in self.visible_categories():
            self.selected[c["id"]] = c["badge"] == "SAFE"
            self._refresh_row(c["id"])
        self._update_footer_hint()

    def select_none(self):
        if self.busy:
            return
        for c in self.visible_categories():
            self.selected[c["id"]] = False
            self._refresh_row(c["id"])
        self._update_footer_hint()

    def _update_footer_hint(self):
        chosen = [c for c in self.visible_categories() if self.selected[c["id"]]]
        total = sum(self.sizes.get(c["id"], 0) for c in chosen)
        if chosen and total:
            self.status.configure(
                text=f"{len(chosen)} selected · {human(total)}", fg=DIM
            )
        else:
            self.status.configure(text="")

    def _set_busy(self, busy):
        self.busy = busy
        for btn in (self.clean_btn, self.rescan_btn):
            btn.configure(bg="#22293A" if busy else btn._base_bg)
            btn.configure(
                fg=FAINT if busy else ("#FFFFFF" if btn is self.clean_btn else TEXT)
            )

    # -- animation -------------------------------------------------------------
    def _animate(self):
        if self.busy:
            self.spin_i = (self.spin_i + 1) % len(SPINNER)
            frame = SPINNER[self.spin_i]
            current = self.status.cget("text")
            if current:
                base = current.lstrip("".join(SPINNER)).lstrip()
                self.status.configure(text=f"{frame} {base}")
            if self.active_cid:
                self.rows[self.active_cid]["size"].configure(text=frame, fg=ACCENT)
        self.root.after(90, self._animate)

    def _count_up(self, target_kb, step=0):
        steps = 22
        eased = 1 - (1 - step / steps) ** 3
        shown = int(target_kb * eased)
        self.result.configure(text=f"✓ Clean successful — freed {human(shown)}")
        if step < steps:
            self.root.after(28, lambda: self._count_up(target_kb, step + 1))

    # -- scan -----------------------------------------------------------------
    def scan(self):
        if self.busy:
            return
        self._set_busy(True)
        self.result.configure(text="")
        label = "Deep scanning…" if self.mode == "deep" else "Scanning…"
        self.status.configure(text=label, fg=DIM)
        cats = self.visible_categories()
        for c in cats:
            self.rows[c["id"]]["size"].configure(text="…", fg=FAINT)
            self._set_row_state(c["id"], "", GREEN)
        threading.Thread(target=self._scan_worker, args=(cats,), daemon=True).start()

    def _scan_worker(self, cats):
        for category in cats:
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
        chosen = [c for c in self.visible_categories() if self.selected[c["id"]]]
        chosen = [c for c in chosen if self.sizes.get(c["id"], 0) > 0]
        if not chosen:
            messagebox.showinfo(
                "Mac Cleaner", "Nothing selected (or selection is empty)."
            )
            return

        confirmed = []
        for category in chosen:
            if category["badge"] == "SAFE":
                confirmed.append(category)
                continue
            if category["id"] == "avd" and emulator_running():
                messagebox.showwarning(
                    "Mac Cleaner",
                    "The Android emulator is running.\n"
                    "Close it first — skipping the wipe.",
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

        self._set_busy(True)
        self.result.configure(text="")
        threading.Thread(
            target=self._clean_worker, args=(confirmed,), daemon=True
        ).start()

    def _clean_worker(self, chosen):
        freed = 0
        issues = []
        for category in chosen:
            cid = category["id"]
            before = self.sizes.get(cid, 0)
            self.events.put(("cleaning", cid, category["name"]))
            outcome = ("ok", "")
            try:
                paths = category["paths"]()
                if category["badge"] == "ADMIN":
                    if paths:
                        ok, detail = delete_admin_paths(paths)
                        if not ok:
                            outcome = ("fail", detail)
                else:
                    delete_paths(paths)
                if cid == "caches":
                    brew_cleanup()
                remaining = du_kb(category["paths"]())
            except Exception as exc:
                outcome = ("fail", str(exc)[:200])
                remaining = before
            # cache dirs are recreated by running apps within seconds, so a
            # small remainder is normal — only flag a real failure to shrink
            if outcome[0] == "ok" and remaining > 51200 and remaining > before * 0.2:
                outcome = ("partial", "")
            freed += max(0, before - remaining)
            self.events.put(("cleaned", cid, (remaining, outcome)))
            if outcome[0] != "ok":
                issues.append((category["name"], outcome))
        self.events.put(("clean_done", freed, issues))

    # -- event pump ------------------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, a, b = self.events.get_nowait()
                if kind == "size":
                    self.sizes[a] = b
                    self.rows[a]["size"].configure(
                        text=human(b) if b else "—", fg=TEXT if b else FAINT
                    )
                elif kind == "cleaning":
                    self.active_cid = a
                    self.status.configure(text=f"Cleaning {b}…", fg=DIM)
                    self._set_row_state(a, "", GREEN)
                elif kind == "cleaned":
                    remaining, (state, detail) = b
                    self.active_cid = None
                    self.sizes[a] = remaining
                    self.rows[a]["size"].configure(
                        text=human(remaining) if remaining else "—",
                        fg=TEXT if remaining else FAINT,
                    )
                    if state == "ok":
                        self._set_row_state(a, "✓ CLEANED", GREEN)
                    elif state == "partial":
                        self._set_row_state(a, "PARTIAL — SOME FILES IN USE", AMBER)
                    elif detail == "cancelled":
                        self._set_row_state(a, "SKIPPED — PASSWORD CANCELLED", AMBER)
                    else:
                        self._set_row_state(a, "FAILED", RED)
                elif kind == "scan_done":
                    self._set_busy(False)
                    self.active_cid = None
                    self._update_footer_hint()
                    self.free_label.configure(text=human(free_disk_kb()))
                elif kind == "clean_done":
                    self._set_busy(False)
                    self.active_cid = None
                    self.free_label.configure(text=human(free_disk_kb()))
                    issues = b
                    if issues:
                        names = ", ".join(name for name, _ in issues)
                        self.status.configure(
                            text=f"Finished with issues: {names}", fg=AMBER
                        )
                        self.result.configure(text=f"Freed {human(a)}", fg=AMBER)
                    elif a == 0:
                        self.status.configure(text="", fg=DIM)
                        self.result.configure(
                            text="✓ Already clean — nothing to remove", fg=GREEN
                        )
                    else:
                        self.status.configure(text="", fg=DIM)
                        self.result.configure(fg=GREEN)
                        self._count_up(a)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)


def main():
    root = tk.Tk()
    MacCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
