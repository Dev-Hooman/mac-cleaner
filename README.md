<p align="center">
  <img src="assets/icon.png" width="160" alt="Mac Cleaner icon">
</p>

<h1 align="center">Mac Cleaner</h1>

A **safe, transparent disk-space cleaner for macOS** with a modern dark UI.
Scans well-known cache and build-artifact locations, shows you exactly what it
found with per-item sizes, and deletes **only what you select** — never your
files, documents, or settings.

![Platform](https://img.shields.io/badge/platform-macOS%2010.15%2B-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-yellow)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

![Mac Cleaner main window](screenshots/main.png)

**Simple scan** covers the always-safe locations. **Deep scan** additionally
discovers project `node_modules` folders, browser profile caches, Xcode
archives and local iPhone/iPad backups.

Animated per-row progress while cleaning, honest per-row outcomes
(`✓ CLEANED`, `PARTIAL`, `SKIPPED`) and a real freed-space total when done:

![Cleaning result](screenshots/success.png)

## Why another cleaner?

Most "cleaner" apps are opaque about what they delete. Mac Cleaner is the
opposite:

- **Every category is listed with its exact path and size** before anything happens
- **You select individually** — nothing is deleted without your say-so
- **Safety badges** on every row:
  - 🟢 `SAFE` — auto-regenerating caches (npm, Gradle, Xcode DerivedData, app caches…)
  - 🟡 `CAUTION` — things with a real cost (Trash, emulator data) — each asks for
    an extra confirmation
  - 🔴 `ADMIN` — root-owned leftovers, deleted via the native macOS password prompt
- **Open source, ~700 lines, zero dependencies** — read exactly what it does

## What it cleans

| Category | Badge | Details |
|---|---|---|
| App & system caches | 🟢 SAFE | `~/Library/Caches`, `~/.cache` (+ `brew cleanup`) |
| JavaScript package caches | 🟢 SAFE | npm `_cacache`/`_npx`, pnpm store |
| Gradle build cache | 🟢 SAFE | `~/.gradle` caches, daemons, wrappers |
| Xcode derived data | 🟢 SAFE | DerivedData, iOS DeviceSupport |
| Editor caches | 🟢 SAFE | VS Code / Cursor cache folders |
| Claude app caches | 🟢 SAFE | VM bundles, GPU/code caches |
| Old Claude CLI versions | 🟢 SAFE | Superseded builds (newest kept) |
| Stremio stream cache | 🟢 SAFE | Cached video streams |
| Expo caches | 🟢 SAFE | Expo Go, APK caches |
| Trash | 🟡 CAUTION | Gone for good — asks first |
| Android emulator data | 🟡 CAUTION | Wipes AVD storage; refuses while the emulator runs |
| iOS simulator devices | 🟡 CAUTION | `~/Library/Developer/CoreSimulator` |
| iOS simulator runtimes | 🔴 ADMIN | `/Library/Developer/CoreSimulator` via password prompt |

**Deep scan** adds:

| Category | Badge | Details |
|---|---|---|
| Project node_modules | 🟡 CAUTION | Found across your projects — `npm install` restores them |
| Browser caches | 🟢 SAFE | Chrome / Brave / Edge profile caches (quit the browser first) |
| Xcode archives | 🟡 CAUTION | Old distribution archives |
| iPhone / iPad backups | 🟡 CAUTION | Local device backups — irreplaceable |

Anything that doesn't exist on your Mac simply shows `—` and is skipped.

## What it will never touch

Your documents, photos, projects, source code, browser profiles, app settings,
passwords, or anything else that doesn't regenerate itself.

## Install

### Option 1 — download the installer (easiest)

Grab `Mac.Cleaner.dmg` from the [latest release](../../releases/latest),
open it, and drag **Mac Cleaner** onto the **Applications** shortcut.
Then eject the disk image — the app runs from Applications.

> **First launch — macOS will block the app** ("Apple could not verify…")
> because it isn't notarized (that requires a paid Apple Developer account).
> Two ways to open it anyway:
>
> 1. Try opening it once, then go to **System Settings → Privacy & Security**,
>    scroll down to *"Mac Cleaner" was blocked*, and click **Open Anyway**; or
> 2. In Terminal: `xattr -rd com.apple.quarantine "/Applications/Mac Cleaner.app"`
>    then open normally.
>
> The app is open source — you can read every line it runs, or build it
> yourself (below) and skip the warning entirely.
>
> The pre-built app is Apple Silicon (arm64). On an Intel Mac, run from
> source instead — it works the same.

### Option 2 — run from source (all Macs)

```bash
git clone https://github.com/Dev-Hooman/mac-cleaner.git
cd mac-cleaner
python3 mac_cleaner.py
```

Requires Python 3.9+ with Tkinter. If Python says Tkinter is missing:

```bash
brew install python-tk
```

## Build the app yourself

```bash
python3 -m venv .venv
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --windowed --name "Mac Cleaner" mac_cleaner.py
# → dist/Mac Cleaner.app
```

## Safety design

- Sizes are measured with `du -skx` (one filesystem, no double-counting of
  mounted images)
- The Android emulator wipe **refuses to run** while an emulator process is alive
- Admin deletions go through `osascript` → the standard macOS password dialog;
  the app never stores or sees your password
- Every deletion error is swallowed per-item, never crashing a whole run

## License

[MIT](LICENSE) — do whatever you like, no warranty.

App icon: broom glyph by [UXWing](https://uxwing.com/broom-cleaning-icon/)
(free for commercial use, no attribution required — credited anyway).
