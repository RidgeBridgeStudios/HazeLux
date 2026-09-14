# Hazelux

[![Linux](https://img.shields.io/badge/Platform-Linux%20%28Debian%20%2F%20Ubuntu%20%2F%20Zorin%29-blue.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green.svg)](#)
[![UI](https://img.shields.io/badge/UI-GTK4%20%2F%20Libadwaita-orange.svg)](#)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)

**Hazelux** is an open-source, native Linux desktop file automation daemon and graphical configuration utility architected for Debian and Ubuntu derivatives, with primary optimization for **Zorin OS**. The system continuously evaluates filesystem events against user-defined declarative rules to automate routine file organization tasks such as sorting, renaming, and cleaning.

---

## Key Architectural Highlights

- **Fast & Unmediated Linux Inotify Monitoring**: Utilizes the Rust-backed `watchfiles` library to stream Linux kernel inotify events without Global Interpreter Lock (GIL) or main-loop starvation.
- **Three-Stat Quiescence Protocol**: Prevents reading partially written payloads (browser downloads, media renders) by verifying 3 consecutive identical stat checks (`st_size`, `st_mtime`) over ~0.70 seconds coupled with non-blocking file lock validation (`O_NONBLOCK | O_RDONLY`).
- **Transactional SQLite WAL Journal**: Records all filesystem mutations across a 5-state lifecycle (`pending` → `staging_written` → `committed` → `reverted` | `failed`), enabling instant one-click Undo and automatic crash reconciliation on startup.
- **Non-Destructive Safe Relocation**: Atomic placeholder reservations (`O_CREAT | O_EXCL`) prevent TOCTOU race conditions; same-device transfers execute via atomic replacement while cross-device moves utilize staging files with byte integrity assertions.
- **Loop Prevention & Disk Thrashing Protection**:
  - `CooldownCache`: 10.0s TTL suppressing destination canonical paths and target inodes.
  - `DestinationEventSuppression`: 15.0s TTL suppressing destinations within actively monitored directories.
  - `CascadingLoopTracker`: Suspends automation for any file inode triggering > 5 actions within 60 seconds.
- **FreeDesktop Trash Undo**: Captures `.trashinfo` metadata and unique `trash:///` URIs, restoring trashed items with `gio trash --restore` and fallback file relocation.
- **Pure Libadwaita Desktop Design**: Clean two-line layout for conditions and actions, adaptive `Adw.NavigationSplitView`, `Adw.ToastOverlay`, dynamic accent/dark theme tracking via `Adw.StyleManager`, and StatusNotifierItem system tray integration.

---

## Phase 1 Feature Matrix

| Feature Domain | Phase 1 MVP Implementation | Architectural Primitives |
| :--- | :--- | :--- |
| **Condition Matching** | File name, extension, file size, modification date, creation date (`st_birthtime`), and EXIF date | POSIX `stat`, Python 3.12+ `os.stat()` birthtime check, `exifread`, 100ms timeout regex engine |
| **Automated Actions** | Relocate (`move`), Duplicate (`copy`), Dynamic Token Rename (`rename`), FreeDesktop Trash (`trash`) | Python `shutil`, `os.replace`, `gio trash` |
| **Collision Handling** | `rename_counter` (auto-increment `(1)`, `(2)`), `skip`, and `overwrite` | Atomic `O_CREAT \| O_EXCL` reservation |
| **Undo / Rollback** | Transactional reverse delta rollback via SQLite WAL journal | Reverse file moves, trash restoration |
| **Filesystem Scope** | Local home directory hierarchy (`~/*`, `--filesystem=home`) | Canonical path resolution within `$HOME` |
| **Desktop Shell** | Application autostart (`~/.config/autostart`), StatusNotifierItem system tray via `pystray` | `libayatana-appindicator3` / D-Bus fallback |

---

## Installation & Distribution

### 1. Native Debian Package (.deb) — Recommended for Zorin OS / Ubuntu

Native `.deb` packages grant unmediated access to kernel inotify events:

```bash
# Build Debian package
dpkg-buildpackage -us -uc -b

# Install
sudo dpkg -i ../hazelux_0.1.0-1_all.deb
sudo apt-get install -f
```

### 2. Flatpak

```bash
flatpak-builder --user --install --force-clean build-dir io.github.hazelux.Hazelux.yml
```

### 3. Local Development Setup

```bash
# Clone repository
git clone https://github.com/hazelux/hazelux.git
cd hazelux

# Create virtual environment with system site packages (for GTK4 & Adw bindings)
python3 -m venv --system-site-packages .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Run test suite
pytest -v tests

# Launch application
python3 -m hazelux.app
```

---

## Running the Daemon

```bash
# Launch with GTK4 / Libadwaita configuration window
hazelux

# Launch in background / autostart mode (minimized to system tray)
hazelux --background
```

---

## Automated Test Suite

The test suite covers:
- **Condition Matching**: String operators, case-insensitivity, 100ms regex timeout under catastrophic backtracking, sparse 10GB file size checks, date offsets, and creation birthtime.
- **Safe Relocation**: Atomic replacement, collision resolution (`rename_counter`), staging integrity, cross-device size mismatch rollback.
- **Loop Prevention**: Cooldown TTL suppression (10s), destination suppression (15s), cascading threshold (>5 actions/60s).
- **Crash Reconciliation & Trash**: Uncommitted pending/staging rollback, orphaned file cleanup, FreeDesktop trash URI matching and restore.
- **Journal Retention**: 30-day committed & 90-day reverted pruning, WAL checkpointing.

```bash
pytest -v tests
```

---

## License

GPL-3.0-or-later. See `debian/copyright` for details.
