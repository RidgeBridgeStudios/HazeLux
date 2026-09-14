# 1. Product Thesis

Hazelux's end state is not "Hazel for Linux." It is **an auditable automation layer for the local filesystem — a rule engine that shows its work.** Every file mutation it performs is journaled and reversible today. What it lacks is the other half of auditability: the ability to *predict* what it will do before it does it, and to *explain* why it did it afterward. When Hazelux reaches its full potential, a user can point it at any folder, see a complete per-file, per-condition explanation of what would happen, execute that plan, watch it appear in a searchable ledger, and undo any piece of it. That loop — rehearse, explain, execute, undo — is the product. Everything else in this roadmap either feeds that loop or feeds off it.

The target power user is a composite I will call the **operator-curator**: a technical professional running Zorin OS, Ubuntu, or Debian on their daily machine who is comfortable with cron and bash but has stopped pretending their shell scripts are a system. Concretely, three archetypes share one pain. (a) The self-hosting developer or sysadmin whose `~/Downloads` is a 10,000-file dumping ground and whose `~/org/cron-sort.sh` rotted when a directory name changed two years ago. (b) The photographer or videographer who dumps camera cards into a project tree and wants ingest sorted by EXIF date, camera, or lens without an Adobe subscription. (c) The researcher or knowledge worker whose scanner, browser, and reference manager deposit a stream of PDFs that need filing by content or date. All three want automation; none will enable it against real data without provable safety. Hazelux already has the safety half (journal, undo, quiescence). The missing half is prediction and explanation.

The killer feature is **Rehearsal Mode: a deterministic, read-only simulation of the entire enabled rule fleet against any local tree, producing a per-file, per-condition explanation and an executable plan.** Not "dry-run" as a checkbox — a first-class artifact: a plan you can inspect, filter, export, and then execute with the same journal protection as any live action. This is the feature that converts fear into workflow. It is why someone switches from shell scripts (scripts have no preview, no undo, no explanation — they rot in crontabs precisely because nobody can see what they will do), from manual organization (rehearsal is what establishes the trust required to stop filing by hand), and from Hazel (which is macOS-only, and whose preview is scoped to a single rule inside its editor per the Noodlesoft manual — https://www.noodlesoft.com/manual/hazel/ — with no fleet-wide simulation of composed rules across a tree, and no exportable, executable plan). The Linux CLI prior art in this class — `organize` (https://github.com/tfeldmann/organize), FileBot, `fclones` — has verification or dedup but no native GUI, no journal-backed undo, and no composed-rule simulation.

Rehearsal Mode is also not just a feature; it is the **platform primitive** the rest of the roadmap depends on. Natural-language rule authoring is unsafe without a preview of the generated rule. A community rule marketplace is reckless without rehearsal-on-import. ML-suggested rules are a liability without per-file explanation of what the suggestion would do. Scheduled cron sweeps are terrifying without a nightly "what would tonight's sweep change" report. Competitors can copy a dedup action in a weekend; they cannot copy the rehearse-explain-execute-undo loop, because it is a system, not a checkbox — and Hazelux already owns the hardest part of it (the transactional journal).

# 2. Feature Roadmap

Effort estimates are developer-weeks for one developer familiar with the codebase. "Deferrable" answers whether deferral breaks another roadmap feature, not whether the feature is valuable.

## Tier A — High leverage, high feasibility (each shippable in 4–9 weeks on top of Phase 1)

### A1. Rehearsal Mode (simulation engine + CLI + execute-plan)
- **Problem it solves:** Users cannot safely enable rules against existing data. Every misconfigured rule is discovered by damage, not by preview.
- **Design sketch:** New module `hazelux/engine/planner.py`. A read-only `os.walk` (sorted, `followlinks=False`, hidden-file option, file cap default 50,000) builds synthetic events from `os.lstat` and calls the existing `evaluate_conditions()` unchanged. One behavior-preserving extraction: the `O_CREAT|O_EXCL` collision-resolution loop from `safe_relocate_file`/`safe_copy_file` moves into a shared `hazelux/engine/collision.py` helper that both Phase 1 actions and the planner call, so planned paths cannot drift from executed paths (existing `tests/test_relocation.py` must pass unchanged after the motion). The planner maintains a `planned_paths` shadow set so intra-plan collisions resolve to `(1)`, `(2)` exactly as execution would. Output: `RehearsalPlan` (JSON-serializable, schema in Section 4). Execution path: `execute_plan()` re-stats each item (`st_ino`, `st_size`, `st_mtime` must match the plan), re-checks `CooldownCache`/`DestinationEventSuppression`/`CascadingLoopTracker` live, and performs mutations only through `JournalManager` — so crash reconciliation covers plan execution for free. Entry points: UI dialog, `hazelux rehearse PATH [--json]`, and an "Execute Plan…" button. Per-file condition verdicts are captured by wrapping `evaluate_single_condition` with a recording variant in the planner (Phase 1 `conditions.py` is untouched).
- **Dependencies:** None. Everything else leans on it.
- **Effort:** [6, 9] weeks (planner + shared collision extraction 3, CLI 1, UI 3, equivalence harness 1–2, overlapping).
- **Risk:** Planner/executor drift if future actions bypass the shared collision helper — mitigated by a property test asserting plan-execution and direct Phase 1 execution produce identical trees. UI volume is the schedule risk, not the engine.
- **Testability:** Golden-fixture trees with expected plan JSON; determinism test (two runs, identical output modulo timestamps); equivalence test (execute plan vs. direct Phase 1 run over the same fixture → identical directory manifests); runtime-guard tests (file vanishes, file mutates, cap exceeded, inode suppressed).
- **Deferrable?** No. It is the prerequisite for C3, C4, D1, D4 and the trust basis for everything destructive.

### A2. Rule Import/Export Bundles
- **Problem it solves:** Rules are trapped in one `rules.json`; users cannot share, back up selectively, or version single rules.
- **Design sketch:** Two file formats, both JSON with `format` and `version` fields: `.hzrule.json` (single rule) and `.hzbundle.json` (`{format: "hazelux-bundle", version: 1, rules: [...], checksum: sha256 of canonical (sorted-key, 2-space) JSON of the rules array}`). Export from a rule's context menu in the existing `Adw.ExpanderRow` editor; import via header-bar button → `Gtk.FileChooserNative` → validate with existing `hazelux.schema.validate_rule()` → conflict dialog (`Adw.AlertDialog`) with three responses: Replace (same `metadata.id`), Keep Both (mint new UUID), Skip. If A1 is present, an "Import and Rehearse…" flow previews the bundle against a chosen folder before committing. Imported rules are tagged `origin: "imported"` in an additive metadata field (schema extension per Section 7's version-on-use policy).
- **Dependencies:** None; soft benefit from A1.
- **Effort:** [2, 3] weeks.
- **Risk:** Low. Main risk is canonical-JSON checksum brittleness across JSON serializers — pinned by generating the checksum only from re-serialized canonical form, never the user's raw file.
- **Testability:** Round-trip test (export → import → deep-equal rule dicts except allowed id changes); tamper test (flip one byte → checksum rejected); schema test (invalid rule in bundle → import blocked with the validator's error list).
- **Deferrable?** Yes, but D4 (signed packs) hard-depends on this bundle format.

### A3. Scheduled Triggers (cron-style sweeps)
- **Problem it solves:** Phase 1 is purely event-driven. "Clean Downloads every night at 02:00" or "sort Photos monthly" — the two most requested patterns — are impossible without a live event.
- **Design sketch:** Additive schema: optional `triggers.schedule` object `{cron: "17 2 * * *", catch_up: false}` (validation via `croniter`, MIT license, https://github.com/kiorky/croniter). A `hazelux/engine/scheduler.py` thread computes the next fire per rule, sleeps with wake-on-config-change (hooked into the existing `ConfigManager.register_reload_callback`), and on fire submits a sweep of that rule's `triggers.paths` to the existing `ThreadPoolExecutor`, calling the existing `process_file()` per file — so `CooldownCache`, `DestinationEventSuppression`, and `CascadingLoopTracker` apply unchanged to scheduled runs. No quiescence wait for sweeps (files at rest), but the `O_NONBLOCK` lock check from the quiescence protocol is reused per file before acting. `catch_up: false` (default) skips windows missed while the machine was off; `true` runs once on startup if a window was missed. Overlap guard: a per-rule `asyncio.Lock` equivalent prevents a second sweep of the same rule while one is running. Tray menu gains "Rehearse tonight's sweep…" if A1 is present.
- **Dependencies:** None.
- **Effort:** [3, 5] weeks.
- **Risk:** Users writing destructive rules that only run on cron discover them slower. Mitigate: first cron fire of any rule runs as a rehearsal report delivered as a desktop notification ("Scheduled sweep would move 214 files — open to review"), with an opt-in `apply_without_report` flag.
- **Testability:** Fake-clock tests (inject time function) for cron alignment, missed-window catch-up, DST-boundary times; integration test that a cron fire with cooldown-active files acts on nothing.
- **Deferrable?** Yes, but it is the highest-demand automation-engine gap and unlocks "nightly report" usage of A1.

### A4. Structured Activity Ledger + Per-Rule Statistics
- **Problem it solves:** Phase 1 logs to stderr and shows 50 raw journal rows. "What did this rule do this month? Why didn't this file move?" are unanswerable.
- **Design sketch:** New database `~/.config/hazelux/activity.db` (WAL) — deliberately **not** `journal.db`, so `hazelux/journal/schema.sql` is untouched. Tables: `events(id, ts, kind, rule_id, rule_name, path, detail_json)` where `kind ∈ {rule_matched, rule_no_match, suppressed_cooldown, suppressed_destination, loop_suspended, action_executed, action_failed, config_changed, schedule_fired}`; and `rule_stats(rule_id, day, matched, acted, bytes_moved, errors)` rolled up daily. A single `ActivityRecorder` object is passed into `RuleEngine` as a new optional constructor argument (default `None` preserves Phase 1 behavior exactly). Condition-verdict detail for `rule_matched`/`rule_no_match` events is written by the A1 planner's recording wrapper when available, keeping traces (B5) cheap later. Retention: 90 days for events, 365 for rollups, pruned alongside the existing startup prune in `app.py`. UI: the existing `RecentActivityGroup` page gains a filter bar (`Gtk.DropDown` for rule + action kind, `Gtk.SearchEntry` for path substring) and a stats header (Adw.ActionRows: files filed, bytes moved, errors, loops prevented, this week/month). CLI export: `hazelux export-activity --json --since 30d` for audit-trail export.
- **Dependencies:** None.
- **Effort:** [3, 5] weeks.
- **Risk:** Write amplification on busy folders (a churny folder can produce thousands of no_match events). Mitigate: sample `rule_no_match` events (record first 20 per rule per day, then aggregate counts only).
- **Testability:** Unit tests per event kind; retention test; read-only Phase 1 regression (engine with no recorder behaves byte-identically); stats rollup correctness against a scripted event sequence.
- **Deferrable?** No for B5 (trace/debugger), which consumes this schema; C4 (learning) also trains from it.

### A5. Extended Action Pack v1 (archive, hardlink, symlink, notify, webhook)
- **Problem it solves:** Move/copy/rename/trash covers relocation but not "zip my screenshots weekly," "mirror into a view with links," or "tell me / tell my server when something happens."
- **Design sketch:** Five new action types, all additive to the `actions[].type` enum with per-type `allOf` constraints mirroring Phase 1's pattern:
  - `archive` `{type: "archive", destination, conflict_strategy, compression_level}` — writes the file into `<destination>/<stem>.zip` using stdlib `zipfile` (Zip64 on, mtime preserved via `ZipInfo.from_file`), then removes the source. Terminal action; journaled as `action_type="archive"` (the journal's `action_type` column is free-form `TEXT` — no schema migration), and undo is implemented as extract-source-and-restore. The editor marks it destructive; rehearsal labels it "destructive: source removed."
  - `hardlink` / `symlink` `{type: ..., destination, conflict_strategy}` — `os.link` / `os.symlink` with the shared collision helper; non-terminal; journaled; undo = unlink. Symlink target is always the source's absolute path; links pointing outside `$HOME` are refused.
  - `notify` `{type: "notify", message}` — token-expanded message posted via `org.freedesktop.Notifications` over D-Bus using `Gio.DBusConnection` (no new dependency; spec: https://specifications.freedesktop.org/notification-spec/latest/). Not journaled (no filesystem mutation).
  - `webhook` `{type: "webhook", url, secret?}` — stdlib `urllib.request` POST of a JSON event payload; if `secret` is set, an `X-Hazelux-Signature: sha256=<HMAC-SHA256>` header signs the body. 3-second timeout, no retries (retry loops are how automators DDoS themselves), failures recorded in the activity ledger. Outbound-only, user-configured — local-first is preserved; nothing requires a cloud service.
  Every new mutating action ships an undo handler registered in a new `hazelux/journal/revert_handlers.py` map keyed by `action_type` (`move_same_dev`, `move_cross_dev`, `copy`, `trash` keep their existing Phase 1 revert paths in `reconcile.py`).
- **Dependencies:** None.
- **Effort:** [3, 6] weeks (archive+undo 1.5, links 1, notify 0.5, webhook 1, tests/UI 1.5).
- **Risk:** `archive` is the first destructive-by-default Phase 1 extension; wrong `destination` can silently zip files into themselves (guard: refuse when destination contains source path). Webhook URLs are a secret-exfiltration vector if rules are shared — A2 bundles must redact `secret` on export.
- **Testability:** Per-action unit tests with fixture trees; undo round-trip for every journaled action type; webhook tested against a local `http.server` in pytest; refusal tests (self-containing archive, outside-home symlink).
- **Deferrable?** No for B4 (pipelines want a richer action vocabulary to branch over); the rest of the roadmap treats it as independent.

### A6. CLI Companion (`hazelux rehearse|run|status|list-rules`)
- **Problem it solves:** Headless and scriptable access. Users want to rehearse from a terminal, script a one-off sweep, or check state over SSH.
- **Design sketch:** New `hazelux/cli.py` dispatched from `bin/hazelux`: no subcommand → GUI (Phase 1 contract unchanged); subcommands route to a non-GTK path. `status` reads `rules.json` + `journal.db` read-only and reports config validity, watched directories, and engine state. `list-rules`, `enable <id>`, `disable <id>` mutate config through `ConfigManager` (atomic save + backup, reload callback fires only if the daemon is in-process). `rehearse PATH [--json] [--limit N]` calls the A1 planner directly with no daemon. `run PATH` executes rules in-process via `RuleEngine` — and **refuses** if the desktop app is running (detected by probing the `io.github.hazelux.Hazelux` bus name with `Gio.bus_watch_name`, plus a pidfile fallback), printing "use the tray's Run Rules Now" instead, because two live engines double-processing is the one corruption mode this feature could introduce. After C1 ships, `run`/`status` become D-Bus clients of the daemon instead.
- **Dependencies:** Soft on A1 (rehearse) and C1 (remote control); independently valuable for status.
- **Effort:** [2, 4] weeks.
- **Risk:** Double-engine foot-gun (mitigated above); drift between CLI and GUI code paths (both must construct the same `RuleEngine`).
- **Testability:** Subprocess end-to-end tests against fixture configs; JSON output schema snapshot tests; refusal test with a mocked bus name present.
- **Deferrable?** Yes; becomes more valuable after C1.

## Tier B — High leverage, moderate complexity (2–4 months each; new subsystems)

### B1. Content Index + Full-Text Condition (FTS5)
- **Problem it solves:** Rules can only see filenames. "File every PDF mentioning 'invoice' into ~/Finance" is the single most requested content-aware behavior.
- **Design sketch:** New subsystem `hazelux/index/` with `~/.config/hazelux/index.db` (WAL). Tables: `files(path PRIMARY KEY, parent, name, ext, size, mtime, hash, content_text, indexed_at)` plus `files_fts` virtual table (`content=` external-content FTS5 over `content_text` and `name`) — FTS5 is confirmed present in the platform SQLite (verified: SQLite 3.45.1 in the Python 3.12 runtime; Debian/Ubuntu build `libsqlite3` ships FTS5 enabled; the code still probes `CREATE VIRTUAL TABLE ... USING fts5` at startup and disables content conditions with a UI banner if absent — spec: https://www.sqlite.org/fts5.html). Indexing scope is the union of enabled rules' `triggers.paths`; incremental: a directory's mtime unchanged → skip subtree; changed → rescan. Content extraction is pluggable: UTF-8/latin-1 sniff for text-ish files, `pdftotext` (poppler-utils) when present for PDFs. New condition field `content` (operator `contains` only, backed by an FTS `MATCH` query with user terms quoted) and `content_regex` (FTS-retrieved candidates then re-checked in Python with the existing 100 ms timeout regex engine). Freshness rule: at evaluation time, if the file's `mtime > indexed_at`, re-index that file inline with a 2-second budget before answering the condition; if the index is unavailable, the condition returns False and logs, mirroring the existing `st_birthtime` unavailable pattern in `conditions.py:140`.
- **Dependencies:** None (C5 reuses its walk machinery).
- **Effort:** [6, 10] weeks.
- **Risk:** Index staleness bugs produce wrong condition answers silently — mitigate with an "Index health" row (coverage %, last full scan) in the UI and a `hazelux index rebuild` command. Binary-file content extraction is a garbage-in minefield — the extractor allowlist is closed, not open.
- **Testability:** Index incremental-correctness tests (touch file → only that file re-indexed); FTS condition truth-table tests; freshness path tests; a Phase 1 regression test proving no-index configs are unaffected.
- **Deferrable?** No for B2, D2, D3, C4 (they consume the index or its hashing column).

### B2. Duplicate Detection (content hashing + review queue)
- **Problem it solves:** Decades of downloads and sync leftovers mean duplicate GBs; no GUI tool on Linux both finds them by content and removes them safely.
- **Design sketch:** B1's `files.hash` column is filled with `blake2b(digest_size=32)` over 1 MB chunks (stdlib, faster than SHA-256 for bulk). New condition `is_duplicate_of` (value: minimum group size, default 2) matches a file whose hash appears ≥N times in index scope. New **non-rule** UI surface: "Duplicate Review" — a grouped list (hash groups sorted by reclaimable bytes), per-group keep policy (newest / oldest / one-per-folder), with actions routed through the journal (trash) so every dedup is individually undoable. Auto-dedup as a *rule action* is opt-in only: `trash` with `is_duplicate_of` conditions plus `safety.require_rehearsal: true`, which makes the rule refuse to fire until the user has rehearsed its scope once (state stored in `activity.db`). Prior art for performance targets: fclones (https://github.com/pkolaczk/fclones) — size-prefix then partial-hash then full-hash is the proven pipeline and is what the indexer does.
- **Dependencies:** Hard: B1. Soft: A1 (rehearsal gate), A4 (ledger records dedup actions).
- **Effort:** [4, 8] weeks.
- **Risk:** False confidence on hash collisions is negligible (blake2b-256) but "same content, different intent" (two `notes.txt` that happen to match) means the review queue must never be skippable in the auto path. Index scope changes can silently change what "duplicate" means — the UI shows the scope.
- **Testability:** Synthetic duplicate trees with known groups and byte-reclaim totals; keep-policy tests; rehearsal-gate refusal test; undo round-trip per trashed duplicate.
- **Deferrable?** Yes; D3 (near-dup images) reuses its review-queue UI but not its hash logic.

### B3. Media Metadata Conditions (audio tags, video containers)
- **Problem it solves:** Photographers and musicians need conditions on *inside* the media file (artist, album, year, duration, camera) — EXIF date alone (Phase 1) is one field of dozens.
- **Design sketch:** New condition fields, all read-only: `audio_artist`, `audio_album`, `audio_title`, `audio_year`, `audio_genre` via **TinyTag** (pure Python, MIT, https://pypi.org/project/tinytag/ — chosen over mutagen deliberately: mutagen is GPLv2-or-later, which is license-compatible with this GPL-3.0-or-later project, but TinyTag is lighter and read-only, which is all this needs); and `video_duration_seconds`, `video_width`, `video_height` via an `ffprobe -print_format json` subprocess (apt `ffmpeg`, treated like the `gio trash` external already used in Phase 1 — condition returns False with a logged warning when ffprobe is absent, same pattern as `st_birthtime`). Values are cached per `(path, mtime)` in a small LRU (media parsing is 10–100 ms; it must not run on every event re-evaluation). Operators reuse the existing string/numeric sets; `*_year` accepts both `is`/`greater_than`/`less_than`.
- **Dependencies:** None.
- **Effort:** [3, 5] weeks.
- **Risk:** Metadata diversity (broken tags, ID3v1 relics) produces confusing no-matches; every extractor failure logs a ledger event with the tag error so users can see why. Malformed media crashing extractors — every call wrapped, per Phase 1's `exifread` handling.
- **Testability:** Fixture audio/video files with known tags (generated by ffmpeg in CI); absence-degradation tests (no ffprobe → False + warning, no crash); cache-correctness tests on mtime bump.
- **Deferrable?** Yes.

### B4. Multi-Step Pipelines with Branching and Failure Policy
- **Problem it solves:** Phase 1 already runs a rule's action list sequentially, but there is no conditional branching ("only if destination was X") and no failure policy (a failed step abandons the rest silently).
- **Design sketch:** Additive per-action fields: `when` (a conditions-group object, same shape as the top-level one, evaluated against the *current* path state at that step — reusing `evaluate_conditions`), and `on_failure ∈ {abort_rule, continue, revert_rule}` (default `abort_rule`, matching Phase 1's implicit behavior). `revert_rule` reverts all `committed` transactions this rule created for this file in this evaluation via the existing revert machinery — the journal makes this possible today with zero schema change. Branching is deliberately expressed as multiple rules with `when` guards rather than nested if/else — a pipeline DSL would be a second language to parse, validate, and explain in rehearsal (see cut list). The planner (A1) gains per-step evaluation so rehearsal shows branch decisions step by step.
- **Dependencies:** Soft: A5 (richer steps to sequence); hard: A1 for rehearsal of `when` guards.
- **Effort:** [5, 9] weeks.
- **Risk:** `revert_rule` across mixed action types (e.g., archive then move) must restore exact pre-rule state — covered by an ordering test matrix over action-type pairs. `when` evaluated against post-move paths is a semantic subtlety: the spec pins it to "the path as the step receives it," and the debugger (B5) displays it.
- **Testability:** Step-ordering matrix tests; failure-injection tests (step 2 of 4 fails → abort vs continue vs revert outcomes); planner equivalence extended to pipelines.
- **Deferrable?** Yes, but D2 (document intake) is designed as a pipeline consumer.

### B5. Evaluation Trace + Rule Inspector ("Why did this file…?")
- **Problem it solves:** The number-one support question for any rule engine is "why didn't my rule fire?" Phase 1 answers it with `logger.debug`.
- **Design sketch:** A4's ledger already stores per-condition verdict detail when the A1 planner's recording wrapper is active. B5 makes it first-class: every `process_file` evaluation optionally records a `trace` object (rule id, per-condition `{field, operator, value, actual, matched, explanation}` where `actual` is the extracted name/size/offset). Given the sampling policy in A4, live tracing is opt-in per rule ("Record evaluation trace" switch, 7-day retention); the always-on path is the inspector's **single-file rehearsal**: paste or browse a path → the planner evaluates it against all enabled rules immediately and renders the full verdict list. UI: new detail pane in the activity page; rows use `emblem-ok-symbolic` / `window-close-symbolic` with human explanations ("name 'IMG_4032' — ends_with 'HEIC' ✓", "modified 41 days ago — threshold: older than 30 days ✗"). This is deliberately **not** a step-through debugger that pauses mid-rule: pausing a thread pool mid-mutation adds race conditions for near-zero explanatory gain over explain-mode plus single-file rehearsal. Cite: this matches how zsh's `xtrace` and Git's `GIT_TRACE` earn trust — explanation at the decision boundary, not an interactive halt.
- **Dependencies:** Hard: A4 (ledger). Soft: A1 (single-file rehearsal reuses the planner).
- **Effort:** [5, 8] weeks.
- **Risk:** Trace volume and privacy (paths in ledger) — covered by A4's retention and a "clear activity data" button.
- **Testability:** Trace-object schema tests; explanation-string golden tests; single-file rehearsal consistency test (verdicts match full-tree rehearsal for that path).
- **Deferrable?** Yes, but it is the UX pay-off of A4 and the trust multiplier for C3/C4.

### B6. Snapshot Action / Overwrite Protection
- **Problem it solves:** `overwrite` collisions and `archive` destroy data. Phase 1's undo covers moves and trash but cannot resurrect an overwritten file.
- **Design sketch:** Additive rule-level object `safety: {snapshot_on_overwrite: true}` (default false to preserve Phase 1 semantics). When enabled, before any `os.replace` that overwrites an existing destination, the destination file is copied (hardlink when same device — `os.link` is O(1) and preserves the bytes exactly — falling back to `shutil.copy2` cross-device) into `~/.local/share/hazelux/snapshots/<txn_id>/<name>`. The snapshot path is recorded in a new additive table `snapshots(txn_id PRIMARY KEY, snapshot_path, created_at)` in `journal.db` (`CREATE TABLE IF NOT EXISTS` — the AGENTS.md-compliant way to extend the journal; `file_transactions` itself is untouched). Undo of an overwrite-with-snapshot restores the snapshot to its original path. Retention: 90 days / 2 GB cap, pruned at startup next to `prune_and_vacuum`. Rehearsal annotates overwrite steps with "snapshot will be taken."
- **Dependencies:** None.
- **Effort:** [3, 6] weeks.
- **Risk:** Snapshot writes into `$XDG_DATA_HOME` are outside watched dirs (no loop risk). Disk pressure from big overwrites — the 2 GB cap with oldest-first eviction, and the UI shows current snapshot usage.
- **Testability:** Overwrite with snapshot → undo restores exact bytes (hash-compared); hardlink-vs-fallback selection tests; retention eviction tests; Phase 1 default-off regression.
- **Deferrable?** Yes standalone; recommended before B2's auto-dedup goes anywhere near `overwrite`.

### B7. Git-Backed Rules History
- **Problem it solves:** `rules.json.bak` is one generation deep. "Undo my last three rule edits" and "what changed in my rules last month" are unanswerable.
- **Design sketch:** Zero config-format changes. A `RulesHistorian` hooks `ConfigManager.register_reload_callback` (fires on every save) and commits the new `rules.json` into a **bare** git repo at `~/.local/state/hazelux/rules-history.git` using plumbing only (`hash-object -w`, `commit-tree`, `update-ref`) via the system `git` binary — no Python git library, no worktree, no `.git` clutter beside user configs. Commit messages come from the edit context (rule renamed, rule added, imported bundle N, reverted to backup). UI: "Rules History" dialog listing commits (date, message, one-line diff summary), with "Restore this version" → validate through `validate_config` → save via `ConfigManager` (which itself commits, so restore is itself reversible). Git absent or init fails → feature silently disabled with one ledger event.
- **Dependencies:** None.
- **Effort:** [2, 4] weeks.
- **Risk:** Low. Blob churn is trivial (a rules.json is a few KB); `gc` runs annually via a reflog expire on startup.
- **Testability:** Commit-per-save tests; restore round-trip; corrupted-repo degradation test (history disabled, app unaffected).
- **Deferrable?** Yes; makes multi-machine rule sync via Syncthing/git remote effectively free (see cut list for why formal sync is rejected).

### B8. Sandboxed User-Script Action
- **Problem it solves:** Power users will eventually want arbitrary logic (call an API, hash-and-rename, hit a REST endpoint). Without a designed escape hatch, they will get it by editing the JSON to point `destination` at `$(rm -rf)`-style abuse or forking the app.
- **Design sketch:** New action `{type: "script", script: "name.py", timeout: 30}` where scripts live in `~/.config/hazelux/scripts/`. **The script never touches the filesystem.** It is executed in a `bubblewrap` subprocess (apt `bubblewrap`; GPL binary invoked as a subprocess — no license interaction) with `--unshare-net --unshare-ipc --unshare-pid --ro-bind /usr --tmpfs /tmp`, receives a JSON event descriptor on stdin (`path`, stat fields, media tags if available), and must exit 0 (match / proceed) or 1 (no match). On stdout it may emit one JSON object with *suggestions only*: `{"rename_to": "...", "move_to": "..."}` — and the daemon validates these against a user-approved roots allowlist and performs the operation itself through the journal. Network access is grantable per-script (`allow_network: true` drops `--unshare-net`) with a permanent warning badge in the editor. If bwrap is absent the action is disabled in the UI (like a missing ffprobe), never silently executed unsandboxed.
- **Dependencies:** None.
- **Effort:** [4, 7] weeks.
- **Risk:** bwrap availability varies (it is in Ubuntu/Zorin mains). Users will ask for FS-write scripts — the answer is the allowlisted suggestion protocol, and the docs must be blunt about it. This is the security-sensitive feature in the roadmap; the suggestion-only contract is what keeps the blast radius at zero.
- **Testability:** Script protocol conformance tests (exit codes, malformed JSON, timeout kill, oversized stdout); sandbox test asserting a script that tries to write fails; suggestion-validation tests (reject outside-allowlist `move_to`).
- **Deferrable?** Yes; nothing else depends on it.

## Tier C — Ambitious (4–12 months; architectural changes)

### C1. Headless Daemon Split + D-Bus API (`hazeluxd`)
- **Problem it solves:** The engine dies when the GTK app quits (today `--background` keeps a whole GUI stack alive for a tray icon). Third-party automation (scripts, file managers, shell extensions) has no sanctioned control surface.
- **Design sketch:** New entry point `hazelux/daemon.py` → installed as `hazeluxd`, owning `ConfigManager` + `JournalManager` + `RuleEngine` inside a `Gio.DBusConnection`-serving main loop, running as a systemd user unit (`hazeluxd.service`, `WantedBy=default.target`, https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html). D-Bus interface `io.github.hazelux.Daemon1` (XML introspection, methods: `ListRules`, `SetRuleEnabled(id, bool)`, `Rehearse(path, options) → plan_handle`, `GetPlan(handle)`, `ExecutePlan(handle, subset)`, `RunRulesNow(paths)`, `GetStats(since)`, `Pause`, `Resume`; signals: `ActionExecuted`, `LoopSuspended`, `ScheduleFired`). The existing GUI becomes a **client**: at startup it owns the `io.github.hazelux.Hazelux` bus name and probes for `Daemon1`; if present, all engine interaction goes over D-Bus; if absent, it embeds the engine exactly as today — so Phase 1 behavior is preserved for every existing user until they opt into the daemon via a preferences switch (which installs the user unit and disables embedded mode). `Run Rules Now`, pause, and undo keep their current tray wiring; under client mode they emit D-Bus calls. The A6 CLI switches from refusal-on-daemon-running to transparent proxying.
- **Dependencies:** Soft: A6, A4 (both get better, neither blocks). This is the hardest structural change in the roadmap and gates C2.
- **Effort:** [10, 16] weeks.
- **Risk:** Two-engine scenarios (daemon + embedded) must be impossible — the bus-name probe is the singleton mechanism and is tested adversarially. PyGObject D-Bus async property handling is fiddly; allocate a spike week. Session-bus-only means no system-level attack surface.
- **Testability:** D-Bus interface tests with `Gio.DBusConnection` in-process peers; daemon/client mode-switch matrix; adversarial double-start test; systemd unit validated by `systemd-analyze verify`.
- **Deferrable?** Deferrable until C2; after that it is load-bearing.

### C2. File Manager Integration (Nautilus/Dolphin context menus)
- **Problem it solves:** The rehearse/run loop should live where the files live: right-click a folder → "Rehearse Hazelux rules here."
- **Design sketch:** Two thin providers over C1's D-Bus: (1) Nautilus via `python3-nautilus` (`nautilus-python`, the standard extension mechanism on Ubuntu/Zorin — package `python3-nautilus`; extension registers menu items on folders and calls `Rehearse`/`RunRulesNow`, opening results in the existing GUI); (2) Dolphin via a KDE service-menu `.desktop` file pair (`X-KDE-Priority` actions invoking `hazelux rehearse`/`hazelux run` CLI, which post-C1 are D-Bus clients). A GNOME Shell quick-settings toggle ("Pause file automation") is included as an optional stretch item using the `Pause`/`Resume` methods — cut it first if the quarter slips. No new engine logic.
- **Dependencies:** Hard: C1 (the D-Bus surface), A1 (rehearse), A6 (CLI path for Dolphin).
- **Effort:** [4, 8] weeks.
- **Risk:** `python3-nautilus` tracks Nautilus C API versions across releases — pin behavior to the versions in Ubuntu 24.04/24.10 and degrade to "Open Hazelux" menu item on failure.
- **Testability:** Nautilus extension logic factored into a testable module (menu construction given a URI); service-menu `.desktop` lint; end-to-end D-Bus call tests.
- **Deferrable?** Yes; it is the visibility win after the daemon exists.

### C3. Local-LLM Natural-Language Rule Authoring
- **Problem it solves:** Condition+action JSON is a programming language. "Move screenshots older than a month into ~/Pictures/Archive" should be a sentence, especially for the non-terminal half of the operator-curator audience.
- **Design sketch:** A "Draft rule from description…" entry in the rule editor opens an `Adw.Dialog` with an `Adw.EntryRow` (description) and provider selection. Two fully local providers: (1) autodetected Ollama (`http://127.0.0.1:11434/api/generate`, `format: "json"`); (2) a bundled llama.cpp path via `llama-cpp-python` (MIT, https://github.com/abetlen/llama-cpp-python) with a user-downloaded GGUF instruct model (a 1.5–3 B class model, ~1–2 GB; the download dialog shows size + sha256; nothing is bundled in the .deb). Generation is **grammar-constrained**: a GBNF grammar derived from the Phase 1 rule schema subset makes malformed JSON impossible at the model layer. The draft is *never* applied directly — it is inserted into the editor as a disabled draft and the dialog offers "Rehearse this draft…" (A1) against a chosen folder. Provider absent/model absent → fallback to a curated template gallery (10 parameterized templates: downloads-cleanup, photo-ingest, pdf-filing, …), which is itself a feature.
- **Dependencies:** Hard: A1 (preview). Soft: A2 (bundle format for draft serialization), B5 (explanation makes drafts auditable).
- **Effort:** [8, 14] weeks (LLM plumbing 2, grammar 1.5, UX 3, template gallery 1, evaluation harness 2 — a fixed 100-prompt benchmark set scored by schema validity + rehearsal diff against hand-written gold rules).
- **Risk:** Wrong-but-valid rules; the grammar only guarantees syntax. The rehearsal-first flow is the mitigation and is non-negotiable. Model quality varies; the benchmark harness pins acceptable drift.
- **Testability:** The 100-prompt benchmark (validity ≥ 99 %, semantic-match ≥ 80 % against golds); provider-mock tests; grammar rejection tests.
- **Deferrable?** Yes. Highest demo value in the roadmap; only build after A1 and B5 make drafts trustworthy.

### C4. Learning Rule Suggestions (ONNX classifier from accepted actions)
- **Problem it solves:** Users with a large hand-organized tree shouldn't have to hand-write rules describing what they already did — their `JournalManager` history *is* the training set.
- **Design sketch:** A user-triggered "Suggest rules…" batch job. Training data: `activity.db` `action_executed` events grouped by rule (Phase 1 provides the seeds: every confirmed move labels `(name, extension, size, parent_dir) → destination_dir`). Features: extension one-hot (top 200 + OTHER), name-token 128-dim hashing vector, log-size bucket, parent-directory one-hot, MIME from libmagic (`python-magic`, MIT). Model: gradient-boosted or linear softmax trained offline with scikit-learn (dev-time dependency only) and **exported to ONNX**; runtime inference is `onnxruntime` (MIT, https://onnxruntime.ai/) — no sklearn in the shipped app. Confidence < 0.7 → no suggestion (the bar stated in the brief, adopted as specified). Output: one draft rule per (source-context, destination) pair above threshold, each carrying `origin: "suggested"`, shown as a card with "Rehearse…" (A1) and "Keep/Discard." Minimum 30 samples per destination before any suggestion; retraining only happens on explicit user action, never in the background.
- **Dependencies:** Hard: A4 (labels), A1 (preview). Soft: B1 (content features improve precision later).
- **Effort:** [10, 16] weeks.
- **Risk:** Cold start (few logged actions → no suggestions) is a UX letdown — the UI states data requirements up front. Label bias (user's own past mess) means suggestions describe the past, not the ideal — positioning as "draft from your history" not "AI organizes for you" is honest and also better product.
- **Testability:** Synthetic history → known suggestions; confidence-threshold boundary tests; ONNX/sklearn parity test on a frozen eval set; rehearsal-integration test.
- **Deferrable?** Yes; nothing depends on it.

### C5. Scale & Reliability Hardening (large trees, self-healing watchers)
- **Problem it solves:** 100k+-file trees (photo libraries, mail archives) stress every layer: initial sweeps, event storms, and inotify watch exhaustion (already surfaced via `utils/inotify_limits.py` and the ENOSPC callback).
- **Design sketch:** Four parts, shippable independently: (1) **Incremental walk cache** in B1's `index.db` (dir mtime → subtree skip) making cron sweeps and rehearsals of huge trees second-run-fast; (2) **Event coalescing** — a 300 ms debounce per (path, change-kind) ahead of quiescence, since editors and browsers fire bursts (watchfiles already batches at the Rust layer; this adds the app-level window); (3) **Parallel evaluation** — `process_file` calls fanned across the existing `ThreadPoolExecutor` with per-file ordering preserved within a single file's rule chain (the only ordering contract that matters; cross-file ordering is already unspecified in Phase 1); (4) **Watcher watchdog** — a 60 s reconciler comparing `get_monitored_directories()` against live watch tasks, re-registering drifted sets, and on ENOSPC degrading affected trees to a 15-minute polling sweep with a persistent `Adw.Banner` (extending the existing `on_enospc` hook and inotify banner). Soak gate: a 100k-file fixture tree processed without unbounded memory growth.
- **Dependencies:** Soft: B1 (cache storage). Parts 2–4 are independent.
- **Effort:** [6, 10] weeks.
- **Risk:** Parallelizing `process_file` must respect `CascadingLoopTracker`'s inode accounting (already lock-guarded) and never reorder actions on the *same* file — enforced by per-file task granularity.
- **Testability:** Soak test (100k files, memory ceiling asserted); debounce correctness under burst; watchdog re-registration fault-injection tests; ENOSPC fallback integration test.
- **Deferrable?** Parts individually yes; the watchdog part should ship before any marketing claim about "large libraries."

## Tier D — Moonshot / overengineered

### D1. What-If FUSE Mount (`hazelux rehearse --mount ~/Preview`)
- **Problem it solves:** A rehearsal plan is a list; some users want to *walk* the post-automation tree in their file manager — see `~/Preview/Photos/2026/05/IMG_4032.heic` before it exists.
- **Design sketch:** `pyfuse3` (LGPL-2.1-or-later, dynamically linked — license-compatible with GPL-3, https://github.com/libfuse/pyfuse3) mounting a read-only overlay backed by an A1 `RehearsalPlan`: the projected tree is served from the plan's path map (planned moves/renames applied virtually; source bytes read through to the origin path); all writes return `EROFS`. fusermount3 user mounts require no root. Unmount on dialog close.
- **Why this is overengineered:** A FUSE filesystem is a kernel-adjacent subsystem with real crash and hang modes, maintained to serve an experience the plan list plus file-manager navigation covers 95 % of. pyfuse3 is a low-traffic project; a breaking kernel/libfuse change could strand the feature.
- **Who this is actually for:** The demo video, screenshot-driven adopters, and photographers who think in directory trees rather than lists. Ship only after A1 has a year of production mileage.
- **Dependencies:** Hard: A1.
- **Effort:** [8, 14] weeks.
- **Risk:** Highest per-value risk in the roadmap; hangs inside a filesystem call take down the file manager, not just Hazelux.
- **Testability:** pytest fixtures driving the mount via `subprocess` + `fusermount -u`; projected-path enumeration tests; EROFS write-refusal tests.
- **Deferrable?** Yes, indefinitely.

### D2. Document Intake Engine (OCR + PDF text-layer filing)
- **Problem it solves:** The Phase 2 placeholder is real pain for scanner users: scanned PDFs are images; no filename or text-layer condition can classify them.
- **Design sketch:** Extends B1's extractor registry: for PDFs with a thin/no text layer (`pdftotext` yields < 200 chars), run OCR at **index time** (never at condition time — conditions query the index; a 5-second-per-file OCR inside a rule evaluation would stall the executor). Stack: `pdftoppm` (poppler-utils) → `tesseract -l eng` (Apache-2.0, apt package) → text into `files_fts`; optional `ocrmypdf` (MPL-2.0, file-level compatible with GPL-3, https://github.com/ocrmypdf/ocrmypdf) invoked via subprocess when installed, for users who want the PDF itself to gain a text layer (`--output-type pdfa`). New action `pdf_rotate`/`pdf_merge` are explicitly *not* in scope here (see cut list); intake means: content condition matches → file → destination. Index-queue UI shows OCR progress and per-file failures.
- **Why this is overengineered:** OCR quality on crumpled receipts is perpetually mediocre, the dependency surface (tesseract language packs) is user-hostile, and the addressable audience — heavy scanner workflows on Linux desktops — is small. The indexer-first architecture caps the damage, but it remains the most dependency-laden feature in Tier B/C range.
- **Who this is actually for:** Researchers and home-office users with Fujitsu/brother-class scanners feeding `~/Scans`; archivists digitizing stacks.
- **Dependencies:** Hard: B1 (index + FTS). Soft: B4 (intake pipelines), B3 (document-oriented conditions).
- **Effort:** [10, 18] weeks.
- **Risk:** Tesseract language-data availability and accuracy complaints are a permanent support channel; mitigate with per-file confidence and a "show me what the OCR read" panel so users can diagnose.
- **Testability:** Synthetic scanned fixtures (rendered text → image → PDF) with known strings; text-layer threshold tests; index-queue failure tests.
- **Deferrable?** Yes; it is the flagship of the content-aware branch, not a prerequisite for anything.

### D3. Near-Duplicate Image Radar (pHash + embeddings)
- **Problem it solves:** Exact-hash dedup (B2) misses burst shots, re-encodes, and cropped copies — where photographers' duplicate GBs actually live.
- **Design sketch:** Index-time enrichment for images: 64-bit dHash/pHash via `imagehash` (BSD-2, https://github.com/JohannesBuchner/imagehash) with Hamming-distance grouping (threshold 8), plus an optional ONNX CLIP ViT-B/32 image encoder (user-downloaded ~350 MB model) for semantic similarity in the same review queue as B2, as a third keep-policy-aware grouping tab. Never auto-acts; review queue only.
- **Why this is overengineered:** Perceptual-hash thresholds are famously content-dependent (false merges on textured or low-contrast series), and a 350 MB model for a niche grouping view is a poor effort-to-delight ratio. B2's exact dedup captures most of the reclaimable bytes for 20 % of the effort.
- **Who this is actually for:** Photographers with deep burst libraries; asset librarians. If Hazelux ever markets itself to that persona specifically, promote this out of Tier D.
- **Dependencies:** Hard: B1 (index), B2 (review queue UX).
- **Effort:** [6, 12] weeks.
- **Risk:** Wrong "near-duplicate" groupings erode trust in dedup entirely; the threshold must be user-visible and adjustable per review session.
- **Testability:** Fixture image sets (true bursts, re-encodes, distinct images) with expected groupings at stated thresholds; embedding-determinism tests.
- **Deferrable?** Yes.

### D4. Signed Rule Packs & Community Index
- **Problem it solves:** Once A2 bundles exist, people will trade rules; importing stranger's automation blind is how you lose a home directory.
- **Design sketch:** A2's bundle gains a `signature` field: detached Ed25519 over the canonical-JSON rules array, verified with `cryptography` (Apache-2.0/BSD, https://github.com/pyca/cryptography). Users pin publisher public keys (paste or import); the UI displays a verified-publisher badge, and unverified bundles open with an extra confirmation. The "index" is deliberately not a server: a signed JSON feed file (list of bundles + hashes + publisher) hosted anywhere static, fetched to a local cache, browsable offline — a Syncthing-friendly, local-first "marketplace." Rehearsal-on-import is the default path.
- **Why this is overengineered:** There is no community yet. Signing infrastructure built before there are publishers to sign is ceremony; the honest sequencing is bundles (A2) → community forms → signing. Until then, checksum + rehearsal covers the trust gap.
- **Who this is actually for:** The community maintainer (future you) and cautious adopters who want to try popular rule packs without audit fatigue.
- **Dependencies:** Hard: A2 (bundle format), A1 (rehearsal-on-import).
- **Effort:** [8, 12] weeks.
- **Risk:** Key management UX (pinning, rotation) is a product in itself; a compromise of the "official" publisher key would be reputationally worse than never having signed anything.
- **Testability:** Sign/verify round-trips; tamper rejection; canonicalization edge cases (unicode in rule names).
- **Deferrable?** Yes; explicitly gated on demonstrated demand.

# 3. Feature Categories to Explore

Coverage of the brief's category list — nine of ten categories are drawn from, with packaging deliberately deferred:

| Category | Features |
| --- | --- |
| Extended automation engine | A1 (plan/execute), A3 (cron sweeps), A6 (`run`), B4 (pipelines, `when`, failure policy) |
| Content awareness | B1 (FTS5 + hashing), B2 (dedup), B3 (media tags), D2 (OCR), D3 (pHash) |
| Advanced actions | A5 (archive, links, notify, webhook), B6 (snapshots) |
| Rule authoring UX | A2 (bundles), B5 (inspector), B7 (git history), C3 (NL authoring + templates), D4 (packs) |
| Observability | A4 (ledger, stats, audit export), B5 (traces) |
| Integrations | A5 (webhook), A6 (CLI), C1 (D-Bus), C2 (file managers, shell toggle) |
| Performance & scale | A1 (walk caps), C5 (coalescing, parallelism, watchdog, incremental cache) |
| Safety & trust | A1 (confirmation UX), B2 (review-gated dedup), B6 (snapshots), B8 (sandbox) |
| Reliability | B7 (rollback), C1 (daemon lifecycle), C5 (self-healing watchers) |
| Packaging & distribution | **Deliberately deferred** — see below |

Two categories get explicit reasoning rather than features. **Packaging & distribution**: Phase 1's distribution strategy (.deb primary, Flatpak secondary) is frozen, and the constraints rule out new targets; beyond compliance, each additional target (PPA, AUR, Snap, AppImage, Nix) is a permanent CI and support tax paid for reach the current user base doesn't yet justify. Revisit immediately after 1.0 if the .deb shows traction. **Reliability** beyond C5's watchdog is mostly *already* Phase 1's strength (WAL reconciliation, pruning, trash restore); the roadmap's reliability additions (B7, C1) target configuration and lifecycle, which are the actual unguarded flanks.

# 4. Killer Feature Deep Dive: Rehearsal Mode

## Motivation

Every automation tool asks the user for something perverse: configure it correctly *before* you have evidence of what it does. Shell scripts fail silently; Hazel's per-rule editor preview shows matching files for one rule at a time; nothing composes. The result is predictable — people write one timid rule ("sort PDFs from Downloads") and never scale to the fleet ("organize my entire home"), because the blast radius of a mistake is invisible. Phase 1 already built the expensive half of the solution: a transactional journal with undo and crash reconciliation. Rehearsal Mode completes the loop by making the *prediction* as trustworthy as the *undo*: the same collision-resolution code, the same rule ordering, the same loop-prevention semantics, evaluated read-only, then executed through the same journal path. The strategic payoff compounds: A3's nightly sweep reports, C3's LLM drafts, C4's suggestions, D4's import flow, and D1's FUSE view are all projections of this one artifact.

## The Plan Artifact

`RehearsalPlan` is a versioned, JSON-serializable document — the roadmap's most-reused data structure.

```json
{
  "plan_version": 1,
  "generated_at": 1726300000.0,
  "root": "/home/gabriel/Downloads",
  "options": {"include_hidden": false, "file_cap": 50000, "read_exif": true},
  "cap_reached": false,
  "rules_snapshot_sha256": "…",
  "summary": {"files_scanned": 12034, "would_act": 214, "skipped_no_match": 11780,
               "skipped_suppressed": 3, "skipped_loop_guard": 2, "errors": 35,
               "actions_by_type": {"move": 180, "trash": 30, "archive": 4}},
  "items": [
    {
      "source": "/home/gabriel/Downloads/IMG_4032.heic",
      "stat": {"inode": 123, "size": 4032211, "mtime": 1726299990.0},
      "matched_rule": {"id": "…", "name": "Photos by extension", "priority": 2},
      "conditions_trace": [
        {"field": "extension", "operator": "is", "value": "heic",
         "actual": "heic", "matched": true,
         "explanation": "extension 'heic' — is 'heic' ✓"},
        {"field": "size_bytes", "operator": "greater_than", "value": 1000000,
         "actual": 4032211, "matched": true,
         "explanation": "size 4,032,211 bytes — greater than 1,000,000 ✓"}],
      "action_plan": [
        {"step": 1, "type": "move", "from": "…/Downloads/IMG_4032.heic",
         "to": "…/Pictures/2026/IMG_4032.heic",
         "conflict_resolution": "none_needed",
         "terminal": true, "destructive": false}],
      "outcome": "would_act",
      "runtime_guards": {"in_cooldown_now": false, "would_trigger_loop_guard": false}
    },
    {
      "source": "…/Downloads/old-diagram (7).png",
      "matched_rule": null,
      "conditions_trace": [
        {"field": "extension", "operator": "is", "value": "pdf",
         "actual": "png", "matched": false,
         "explanation": "extension 'png' — is 'pdf' ✗"}],
      "outcome": "skipped_no_match",
      "action_plan": [], "runtime_guards": {}
    }
  ]
}
```

Item `outcome ∈ {would_act, skipped_no_match, skipped_suppressed, skipped_loop_guard, skipped_cap, error}`. Two semantics deserve pinning because agents will get them wrong without this paragraph. First, **intra-plan collision projection**: the planner maintains a `planned_paths` set; a rename/move target already in the set (or on disk) resolves through the shared collision helper exactly as execution would, so two files targeting `report.pdf` plan to `report.pdf` and `report (1).pdf`. Second, **planner/executor identity**: the only permitted touch of Phase 1 internals is the behavior-preserving extraction of the `O_CREAT|O_EXCL` collision loop from `actions.py` into `hazelux/engine/collision.py`, imported by both `safe_relocate_file`/`safe_copy_file` and the planner; `tests/test_relocation.py` passing unchanged is the gate that this extraction changed nothing.

## Engine Design

New module `hazelux/engine/planner.py`, plus one thin shared module `hazelux/engine/collision.py`. Public surface:

```
plan_for_tree(root, rules, *, include_hidden, file_cap, read_exif, only_rule_ids) -> RehearsalPlan
plan_for_file(path, rules) -> PlanItem            # B5's single-file rehearsal
execute_plan(plan, *, item_filter, journal_manager,
             progress_cb, cancel_event) -> ExecutionReport
plan_to_json(plan) -> dict      # export + persistence
```

`plan_for_tree` walks with `os.walk(..., followlinks=False)`, deterministic ordering (directories and files sorted), skipping `.staging_*` names (matching `run_rules_on_directory`'s existing convention), applying `file_cap` and recording `cap_reached`. For each file it reuses `_get_matching_rules_for_path` semantics: enabled rules whose trigger paths (recursive or parent-exact) contain the file, evaluated in ascending `metadata.priority`. Conditions run through a `RecordingConditionEvaluator` that wraps `evaluate_single_condition` and captures `(actual, matched)` per rule — Phase 1's `conditions.py` is imported, never modified. Actions project through a `PlannerActionEngine` that mirrors the Phase 1 loop's `current_path` threading and `is_terminal` semantics (move and trash terminal, copy not, per `runner.py:172–254`), computing `to` paths via `collision.resolve_destination()` without touching the disk (existence checks consult disk **plus** `planned_paths`). Expensive conditions (`exif_date`, later media/OCR) respect `read_exif`/index availability and are marked `costly: true` in traces.

`execute_plan` is deliberately *not* a bulk replay of recorded steps. Per item it: (1) re-stats and compares `inode/size/mtime` against the plan — any drift marks the item `skipped_runtime_drift` and continues; (2) re-checks `CooldownCache`, `DestinationEventSuppression`, and `CascadingLoopTracker.is_suspended()` live; (3) calls `loop_tracker.record_action()` before each step exactly as `process_file` does, so a plan that would trip the 5-actions/60 s guard is stopped by the same guard at execution; (4) performs the mutation through the Phase 1 action functions with `JournalManager`, so transactions, WAL reconciliation, and one-click undo apply unchanged; (5) reports per-item results into `activity.db` as normal `action_executed` events. Execution runs on the existing `ThreadPoolExecutor` with progress via `progress_cb` and cooperative cancellation.

## UX Flow (GTK4/libadwaita)

**Entry points.** Header bar of the existing detail page: a new `Adw.ButtonContent` button "Rehearse…" beside the existing "Run Rules" button (`window.py:339`). Tray menu: "Rehearse…" item above "Run Rules Now" (`tray.py:102–104`). CLI: `hazelux rehearse PATH [--json] [--limit N] [--rules FILE]`.

**Dialog — `RehearsalDialog` (an `Adw.Dialog`, not a window, per current libadwaita guidance: https://gnome.pages.gitlab.gnome.org/libadwaita/doc/1-latest/).** Phase 1 — *Setup*: an `Adw.ToolbarView` with `Adw.HeaderBar` (title "Rehearsal", close button) over a scrollable `Adw.Clamp(maximum_size=700)` containing: an `Adw.PreferencesGroup` "Scope" with an `Adw.ActionRow` "Folder" + `Gtk.Button` "Choose…" opening `Gtk.FileChooserNative` (pre-filled with the selected trigger path), an `Adw.SwitchRow` "Include hidden files" (default off), an `Adw.SpinRow` "Maximum files" (range 100–1,000,000, default 50,000), an `Adw.SwitchRow` "Read EXIF and media metadata (slower)" (default on); an `Adw.PreferencesGroup` "Rules" listing every enabled rule as an `Adw.SwitchRow` (all on, individually toggleable — this is also how users test drafts and imported bundles); footer `Adw.ButtonContent` "Run Rehearsal" (suggested-action style). Phase 2 — *Running*: the same view swaps to a `Gtk.ProgressBar` (pulse while walking, fraction once file count estimate stabilizes), a live counter label ("9,214 / ~12,000 files"), and an `Adw.Button` "Stop". Runs happen on a worker thread; every UI update is marshalled with `GLib.idle_add` — the Phase 1 main-loop rule applies verbatim.

**Phase 3 — *Results*: a two-pane layout inside the dialog (`Adw.NavigationSplitView`, matching the app's existing pattern).** Sidebar pane, top to bottom: a summary `Gtk.FlowBox` of six stat cards (files scanned, would act, no match, suppressed/loop-guard, errors, actions by type as chips); an `Adw.ToggleGroup` filter — All / Would act / Skipped / Errors — bound to a `Gtk.FilterListModel` chain; a `Gtk.SearchEntry` filtering on path substring (via `Gtk.StringFilter`); and the item list as a `Gtk.ListView` over `Gtk.SingleSelection` (factory `Gtk.SignalListItemFactory`, rows built from an `Adw.ActionRow`: title = basename, subtitle = parent dir, suffix = action-type chip + outcome icon). Content pane ("detail"): an `Adw.HeaderBar`-less `Adw.ToolbarView` with a `Gtk.Stack` holding (a) empty state ("Select a file"), (b) detail: source path row, matched-rule row (rule name + priority, or "No rule matched"), a `Adw.PreferencesGroup` "Condition checks" where each condition renders as an `Adw.ActionRow` with `emblem-ok-symbolic` (accent) or `window-close-symbolic` (error) prefix icon and the explanation string as subtitle, and an `Adw.PreferencesGroup` "Planned actions" listing steps (step number, type chip, `from → to` as two wrapped lines, conflict resolution line, "destructive" tag in orange where `destructive: true`). Footer: `Adw.ButtonContent` "Export Plan…" (`Gtk.FileChooserNative` save, JSON), and a destructive-action `Gtk.Button` "Execute Plan…".

**Execution confirmation and feedback.** "Execute Plan…" opens an `Adw.AlertDialog` summarizing what will happen and what is irreversible: "Execute 214 planned actions on /home/gabriel/Downloads? 180 moves, 30 files to Trash, 4 archives. The 4 archives remove their sources; snapshots are enabled for 2 overwrites." Responses: Cancel (default), Execute (destructive appearance). During execution the detail pane shows a progress list with per-item check marks; completion shows `Adw.Toast` "Executed 212 of 214 planned actions — 2 skipped (changed on disk)" with a "Undo" button wired to the existing `TransactionRow.execute_undo` path (`activity.py:129`). No toast auto-dismissal for destructive batches; the batch's txn list is also reachable in the activity page filtered by the plan's execution window.

**Failure states.** `cap_reached` renders a persistent `Adw.Banner` above the list: "Stopped at 50,000 files — raise the limit or rehearse a narrower folder." Per-file errors (permission, vanished) are items with `outcome: error` and a readable reason in the detail pane — they never abort the walk. If zero rules are enabled the dialog's Run button is insensitive with a hint subtitle.

## Data Model and Persistence

In-session plans live in memory (`Gio.ListStore` of `PlanItem` wrappers). Exported/persisted plans go to `~/.local/state/hazelux/rehearsals/<epoch>.json` (XDG_STATE_HOME; auto-pruned after 30 days) whenever the user exports *or* executes, giving every batch an audit artifact; `rules_snapshot_sha256` ties the plan to the exact configuration that produced it (B7 later lets users diff that snapshot). The plan JSON schema is versioned (`plan_version`) so future fields (C4 confidences, D2 OCR excerpts) extend it without breaking old exports.

## Failure Modes

| Failure | Handling |
| --- | --- |
| File vanishes between rehearsal and execution | Re-stat mismatch → item skipped as `runtime_drift`, counted in report |
| File modified between rehearsal and execution | Same inode/size/mtime guard → skipped; re-rehearse offered |
| Plan exceeds file cap | Walk stops at cap, `cap_reached: true`, banner shown; execution refuses on capped plans unless `--allow-partial` |
| Permission errors during walk | Per-item `error` outcome with errno text; walk continues |
| Symlink loops / dir symlinks | `followlinks=False`; symlinks appear as `skipped_no_match` items with explanation |
| User executes plan while daemon processes the same folder | Live guard checks (cooldown/destination-suppression/loop tracker) skip contended items; journal prevents double-application of any single move |
| Walk of a 500k-file tree | Cap default 50k; streaming into the list store in 200-item batches via `GLib.idle_add`; memory bounded by cap |
| Cancel mid-walk / mid-execution | Walk: results so far are valid (partial, flagged). Execution: per-item granularity — completed items are journal-committed, remaining items untouched, report says so |
| Crash during plan execution | Standard Phase 1 startup reconciliation recovers pending/staging transactions — no new machinery |
| Rules change between rehearsal and execution | `rules_snapshot_sha256` mismatch → Execute button disabled with "Rules changed since rehearsal — re-run" |

## Test Plan

1. **Golden fixtures.** Five checked-in fixture trees (downloads-mix, photo-ingest, collision-heavy, deep-nesting, permission-denied) each with a committed expected `RehearsalPlan` JSON; CI asserts byte-equal plans (modulo timestamps).
2. **Determinism.** Two consecutive runs over the same tree produce identical plans except `generated_at`.
3. **Planner/executor equivalence (the load-bearing property).** For each fixture and a seeded RNG of rule sets: execute the plan, snapshot the resulting directory manifest (paths, sizes, hashes); reset; run Phase 1's `run_rules_on_directory` directly over the same fixture; assert identical manifests. This test is what licenses the phrase "the plan is the truth."
4. **Runtime guards.** Vanish/mutate/suppress files between plan and execute; assert skip outcomes and report counts. Loop-guard: a plan with 6 renames of one inode is cut off at 5 by `CascadingLoopTracker` at execution.
5. **Collision projection.** Five files targeting one destination plan `(1)…(4)` suffixes; execution reproduces exactly those names.
6. **Schema/export.** `plan_to_json` round-trips; `rules_snapshot_sha256` changes when any rule field changes.
7. **UI smoke.** Headless `xvfb-run` instantiation of `RehearsalDialog` over a fixture; filter/search/model-count assertions at the model layer (GTK widget tree kept thin over a testable `RehearsalResultsModel`).
8. **CLI.** `hazelux rehearse fixture --json` end-to-end diff against the golden plan; `--limit` behavior; exit codes (0 plan ok, 2 cap reached, 3 config invalid).

## Rollout Strategy

Ship in two steps inside the same minor release train. **0.3.0-alpha1**: planner, `collision.py` extraction (gated by the untouched Phase 1 test suite), CLI, JSON export — usable by scripts and reviewers, zero UI risk. **0.3.0**: the `RehearsalDialog`, tray item, and Execute-Plan path. No configuration or schema migration exists (the plan artifact is new and versioned); no telemetry; docs add a "Rehearsal" chapter positioned before "Rules" because it changes how every other feature is sold. Immediately after release, wire the two cheapest dependent flows: A3's first-fire rehearsal report and A2's "Import and Rehearse," which convert the engine into visible product value within weeks.

# 5. Dependency Graph

```
INDEPENDENT ROOTS:            A2, A3, A4, A5, B1, B3, B6, B7, B8

A1 Rehearsal ──────────────► A6 CLI ───────────────► (C1 turns CLI into D-Bus client)
     │
     ├──────────────────────► C3 NL Authoring ◄──── A2 bundles (draft format)
     │                              ▲
     │                              └── B5 Inspector (auditable drafts)
     ├──────────────────────► C4 Suggestions ──► D4 Signed Packs ◄── A2
     │                              ▲                    (A2 is hard prereq)
     └──────────────────────► D1 FUSE Mount

A4 Ledger ──► B5 Trace/Inspector ──► C1 Daemon Split ──► C2 FM Integration
     └────────► C4 (training labels)

B1 Index ──► B2 Dedup ──► D3 Near-Dup Radar
     ├────────► D2 OCR Intake ──► (B4 pipelines consume it)
     └────────► C5 Scale Hardening (walk cache)

A5 Action Pack ──► B4 Pipelines (richer steps)
B6 Snapshots ──► (recommended before B2 auto-dedup uses overwrite)
```

| Feature | Hard dependencies | Soft dependencies |
| --- | --- | --- |
| A1 Rehearsal | — | — |
| A2 Bundles | — | A1 |
| A3 Cron triggers | — | A1 (first-fire report) |
| A4 Activity ledger | — | — |
| A5 Action pack | — | — |
| A6 CLI | — | A1, C1 |
| B1 Content index | — | — |
| B2 Dedup | B1 | A1, A4, B6 |
| B3 Media conditions | — | — |
| B4 Pipelines | — | A5, A1 |
| B5 Inspector | A4 | A1 |
| B6 Snapshots | — | — |
| B7 Git history | — | — |
| B8 Script sandbox | — | — |
| C1 Daemon split | — | A6, A4 |
| C2 FM integration | C1 | A1, A6 |
| C3 NL authoring | A1 | A2, B5 |
| C4 Suggestions | A4, A1 | B1 |
| C5 Hardening | — | B1 |
| D1 FUSE mount | A1 | — |
| D2 OCR intake | B1 | B4 |
| D3 Near-dup radar | B1, B2 | — |
| D4 Signed packs | A2 | A1 |

**Critical path.** The longest chain to the end state is **A1 → A4 → B5 → C1 → C2**: rehearsal, then the ledger that records evaluations, then the inspector that explains them, then the daemon split that exposes everything over D-Bus, then the file-manager integration that puts it in front of the user's files. A parallel spine — **B1 → B2 → C4 → (C3)** — builds the content-intelligence branch and converges on the same authoring UX. Both spines start at A1, which is the only feature whose delay delays everything; A3, A5, B6, B7, and B8 can be interleaved anywhere without blocking either spine.

# 6. Cut List

- **Cloud sync service / hosted rule sharing** — violates the local-first hard constraint; D4's signed static feed is the local-first substitute.
- **Formal multi-device rule sync with conflict UI** — `rules.json` is a single small file that already syncs via Syncthing or git (B7 makes history safe); building merge machinery for a file that changes a few times a month is infrastructure without a user.
- **PPA, AUR, Snap, AppImage, Nix flake** — Phase 1's distribution strategy is frozen, and each new target is a permanent CI/support tax; revisit post-1.0 on evidence of traction.
- **Windows / macOS ports, web app, mobile** — excluded by constraint and by focus.
- **Custom rule DSL (YAML/HCL/INI)** — duplicates the existing JSON schema + GUI builder as a second parser to validate, document, and explain in rehearsal; strictly worse than the editor plus bundle format.
- **Email/SMTP notification action** — requires credential storage and produces spam risk; libnotify (`A5 notify`) and webhooks cover every legitimate use.
- **Metadata-rewriting actions (writing EXIF/XMP into files)** — irreversible mutation of user content with a high blast radius; read-only metadata conditions (B3) are safe and sufficient.
- **Local facial recognition for photo filing** — heavyweight models, slow CPU inference, and an unacceptable failure mode (mislabeled family photos auto-filed by a daemon).
- **Automatic (non-interactive) conflict resolution for multi-writer scenarios** — no safe default exists when two processes mutate the same tree; guards and skips (A1 execution, C5 watchdog) are the honest behavior.
- **GPU acceleration for ML features** — onnxruntime CPU inference of a small classifier or CLIP image encoder is more than fast enough at desktop event rates; GPU drivers are a support nightmare.
- **Watching network mounts and removable media** — inotify does not deliver events over NFS/SMB, and removable-media semantics (unplug mid-move) are unbounded risk; Phase 1 already scopes to local `$HOME` and cross-device staging exists for the edge cases.
- **One-click "organize my entire home directory" wizard** — maximizes the blast radius at exactly the moment users trust the product least; rehearsal-plus-execution is the safe version of the same value.
- **Bespoke IDE/VS Code extension** — the D-Bus API (C1) is the sanctioned third-party surface; a dedicated extension duplicates it for one editor's audience.
- **PDF content rewriting (merge/split/rotate as rule actions)** — those operations rewrite user documents in place; if ever built, they belong behind the snapshot system (B6) with an explicit destructive contract, and the demand does not justify that ceremony today.
- **Real-time collaborative rule editing** — there is no team surface in a local-first desktop daemon; multi-user fiction without a backend.

# 7. Migration and Compatibility

Global policy first, because four features touch `rules.json`: the schema currently sets `additionalProperties: false` everywhere (`schema.py:12`), so **any** new optional field breaks old validators. Therefore the file `version` field becomes *feature-driven*: the file stays at `version: 1` unless it contains a construct unknown to v1; a file using v2 constructs (`schedule`, `safety`, `when`, new condition/action types) is written as `version: 2`, and the v2 validator accepts both v1 files (missing optional fields, defaults applied) and v2 files. Old Hazelux binaries loading a v2 file will show the existing "configuration invalid" banner rather than corrupting anything (`config.py:71`) — the UI warns about this on save when the file was previously v1, and the docs note the one-way street. No loader ever rewrites a v1 file to v2 except on an explicit user edit. `journal.db`: `file_transactions` is never altered — new action types are safe because `action_type` is unconstrained `TEXT` (only `state` has a CHECK), and new associations (B6 snapshots) use additive `CREATE TABLE IF NOT EXISTS` tables, the AGENTS.md-compliant extension path. The quiescence protocol, cooldown TTLs, cascade thresholds, and the tray contract are modified by no feature in this roadmap; A3 *reuses* the loop-prevention machinery and the tray gains additive menu items only.

| Feature | Touches | Migration path |
| --- | --- | --- |
| A1 Rehearsal | New artifact only | None; plans versioned via `plan_version`; the one Phase 1 touch (collision extraction into `collision.py`) is behavior-preserving and gated by the existing test suite |
| A2 Bundles | New files only | None; exports redact webhook `secret` |
| A3 Cron triggers | `rules.json` | Optional `triggers.schedule`; version-on-use policy above; v1 files load unmodified (default filesystem-only behavior) |
| A4 Ledger | New `activity.db` | None; `RuleEngine`'s new recorder argument defaults to `None` (Phase 1 behavior byte-identical) |
| A5 Action pack | `rules.json` | New action types + per-type `allOf` constraints; v2-on-use; new `action_type` values journal with no `journal.db` change; undo handlers registered per type |
| A6 CLI | New entry path | None; `hazelux` with no subcommand launches the GUI exactly as Phase 1 |
| B1 Index | New `index.db` | None; absent index degrades `content` conditions to False with a logged warning (same pattern as `st_birthtime`) |
| B2 Dedup | Index schema | Additive columns/tables in `index.db` only |
| B3 Media conditions | `rules.json` | New condition fields, v2-on-use; missing extractors degrade to False + warning |
| B4 Pipelines | `rules.json` | Optional `when`/`on_failure` per action; v2-on-use; default `on_failure: abort_rule` reproduces Phase 1's implicit behavior exactly |
| B5 Inspector | `activity.db` | Trace columns additive; live tracing opt-in per rule |
| B6 Snapshots | `journal.db` | Additive `snapshots` table (`CREATE TABLE IF NOT EXISTS`); `file_transactions` untouched; feature off by default |
| B7 Git history | New state dir | None; zero config-format change; silently disabled if git unavailable |
| B8 Script sandbox | `rules.json` | New action type, v2-on-use; disabled when bwrap absent |
| C1 Daemon split | Lifecycle only | Explicit opt-in: existing users keep embedded-engine behavior; config, journal, schema, and tray untouched; bus-name probe enforces single engine |
| C2 FM integration | New packages | Optional `python3-nautilus` dependency; degrades to menu stub on absence |
| C3 NL authoring | None persistent | Drafts enter via the normal editor + save path; model download lives in XDG data |
| C4 Suggestions | `activity.db` reads | Read-only consumer; suggestions are ordinary v2 rules carrying `origin: "suggested"` |
| C5 Hardening | Engine internals | Debounce/parallelism flags default to Phase 1-equivalent behavior; watchdog extends the existing `on_enospc` hook |
| D1 FUSE mount | None | Read-only, user-invoked, unmounts on close |
| D2 OCR intake | `index.db` | Additive extractor in the registry; absent tesseract degrades to B1 behavior |
| D3 Near-dup radar | `index.db` | Additive `phash` column; backfill is a user-triggered re-index |
| D4 Signed packs | A2 bundle format | Additive `signature` field; `bundle version: 2`; v1 bundles still import (verified badge simply absent) |

The one deliberate compatibility concession: old Hazelux versions cannot read v2 configuration files. Refusing to sneak new fields into a `version: 1` file is what keeps the frozen Phase 1 validator honest; the save-time warning and the documented one-way street are the least disruptive mitigations available.

# 8. Recommended Next Three Features

**1. Rehearsal Mode + plan execution (A1) — weeks 1–8.** Nothing else in this document is safe, sellable, or even honest without it: the nightly-sweep report, LLM drafts, suggestions, and import previews all project this engine, and the collision extraction is the only piece of Phase 1 internals any roadmap feature ever needs to touch. It is also the product's story in one demo — rehearse, explain, execute, undo — and it ships at low risk because it is read-only until the user presses one explicit, confirmed button. Landing it first means every subsequent feature inherits an acceptance harness (the plan-equivalence tests) that will catch regressions in Phase 1 itself.

**2. Structured activity ledger + per-rule statistics (A4) — weeks 9–12.** Cheap (a second SQLite database and an optional recorder), invisible when done well, and load-bearing twice over: it is the substrate B5's inspector reads and the training data C4 learns from, and it converts the journal — which today only answers "what just happened" — into an answerable record of "what has this automation done for me this month." The sampling policy and the no-recorder default keep it from taxing Phase 1 users. Shipping it second means traces exist by the time anyone asks "why didn't my rule fire?" for the hundredth time.

**3. Scheduled triggers with first-fire rehearsal reports (A3) — weeks 13–15.** This completes the automation model: Phase 1 + A3 means both "when files appear" and "while I wasn't looking" are covered, which is what the operator-curator persona actually asks for first ("clean Downloads nightly"). The first-fire-rehearsal-report design makes cron sweeps trustworthy out of the box by reusing A1 rather than inventing new safety machinery, and the additive schema change is the lowest-risk rules.json extension in the roadmap. Together the three fit a two-person team inside one quarter with room to spare for the A4 sampling bugs and the 0.3.0 packaging work — and each of the three is independently shippable if the quarter compresses.
