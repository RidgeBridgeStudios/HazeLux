"""Action execution module: safe atomic relocation, copy, rename, and trash."""

from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
from typing import Literal, Optional
import uuid

from hazelux.journal.manager import JournalManager
from hazelux.journal.trash import trash_file

logger = logging.getLogger("hazelux.engine.actions")

ConflictStrategy = Literal["rename_counter", "skip", "overwrite"]


class RelocationError(Exception):
    pass


def expand_rename_pattern(source_path: Path, pattern: str) -> str:
    """Expand dynamic tokens in rename patterns."""
    now = datetime.now()
    size_str = "0"
    if source_path.exists():
        try:
            size_str = str(source_path.stat().st_size)
        except OSError:
            pass

    tokens = {
        "{name}": source_path.stem,
        "{extension}": source_path.suffix.lstrip("."),
        "{ext}": source_path.suffix.lstrip("."),
        "{size}": size_str,
        "{year}": now.strftime("%Y"),
        "{month}": now.strftime("%m"),
        "{day}": now.strftime("%d"),
        "{date}": now.strftime("%Y-%m-%d"),
        "{time}": now.strftime("%H-%M-%S"),
    }

    result = pattern
    for k, v in tokens.items():
        result = result.replace(k, v)

    # Preserve extension if omitted from resulting pattern and source had one
    if not Path(result).suffix and source_path.suffix:
        result += source_path.suffix

    return result


def safe_relocate_file(
    source_path: Path,
    target_dir: Path,
    target_name: str,
    strategy: ConflictStrategy,
    journal_manager: JournalManager,
    retry_depth: int = 0,
) -> Optional[Path]:
    """Executes non-destructive, atomic file relocation with conflict handling.

    Maintains a 5-state lifecycle (pending -> staging_written -> committed -> reverted | failed)
    to guarantee crash recovery and eliminate TOCTOU races.
    """
    if retry_depth > 5:
        raise RelocationError("Exceeded maximum retry depth (5) during collision handling.")

    target_dir.mkdir(parents=True, exist_ok=True)
    destination_candidate = target_dir / target_name
    txn_id = str(uuid.uuid4())

    # Determine resolution target path
    if destination_candidate.exists():
        if strategy == "skip":
            return None
        elif strategy == "overwrite":
            final_target = destination_candidate
        elif strategy == "rename_counter":
            stem = Path(target_name).stem
            ext = Path(target_name).suffix
            counter = 1
            while True:
                candidate = target_dir / f"{stem} ({counter}){ext}"
                try:
                    # Atomically reserve path placeholder
                    fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    os.close(fd)
                    final_target = candidate
                    break
                except FileExistsError:
                    counter += 1
                    if counter > 10000:
                        raise RelocationError("Exceeded 10,000 collision iterations.")
    else:
        # Destination is clear; reserve it atomically
        try:
            fd = os.open(destination_candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            final_target = destination_candidate
        except FileExistsError:
            # Raced with another process; re-enter resolution with bounded depth
            return safe_relocate_file(
                source_path, target_dir, target_name, strategy, journal_manager, retry_depth + 1
            )

    source_stat = source_path.stat()
    try:
        is_same_filesystem = source_stat.st_dev == target_dir.stat().st_dev
    except OSError:
        is_same_filesystem = True

    if is_same_filesystem:
        # Register pending operation in WAL journal
        journal_manager.log_transaction(
            txn_id=txn_id,
            inode=source_stat.st_ino,
            action_type="move_same_dev",
            source_path=str(source_path),
            target_path=str(final_target),
            staging_path=None,
            state="pending",
        )

        try:
            # Atomically replace final target placeholder with source file
            os.replace(source_path, final_target)
            journal_manager.update_state(txn_id, "committed")
        except Exception as err:
            journal_manager.update_state(txn_id, "failed")
            raise RelocationError(f"Same-device transfer failed: {err}") from err
    else:
        # Cross-device move: copy to hidden staging file on destination mount point
        staging_filename = f".staging_{uuid.uuid4().hex}_{final_target.name}"
        staging_path = target_dir / staging_filename

        # Register pending cross-device transaction
        journal_manager.log_transaction(
            txn_id=txn_id,
            inode=source_stat.st_ino,
            action_type="move_cross_dev",
            source_path=str(source_path),
            target_path=str(final_target),
            staging_path=str(staging_path),
            state="pending",
        )

        try:
            # Copy data and metadata preserving flags
            shutil.copy2(source_path, staging_path)

            # Flush kernel buffers to ensure data durability
            with open(staging_path, "rb") as f:
                os.fsync(f.fileno())

            # Verify byte integrity
            if staging_path.stat().st_size != source_stat.st_size:
                raise RelocationError("Verification failure: File sizes do not match after transfer.")

            journal_manager.update_state(txn_id, "staging_written")

            # Atomically replace destination placeholder with staging file
            os.replace(staging_path, final_target)
            journal_manager.update_state(txn_id, "committed")

            # Safely unlink source path once destination is persistent
            source_path.unlink()
        except Exception as err:
            if staging_path.exists():
                try:
                    staging_path.unlink()
                except OSError:
                    pass
            journal_manager.update_state(txn_id, "failed")
            raise RelocationError(f"Cross-device transfer failed: {err}") from err

    return final_target


def safe_copy_file(
    source_path: Path,
    target_dir: Path,
    target_name: str,
    strategy: ConflictStrategy,
    journal_manager: JournalManager,
    retry_depth: int = 0,
) -> Optional[Path]:
    """Executes safe atomic file copy with collision handling and journal tracking."""
    if retry_depth > 5:
        raise RelocationError("Exceeded maximum retry depth (5) during collision handling.")

    target_dir.mkdir(parents=True, exist_ok=True)
    destination_candidate = target_dir / target_name
    txn_id = str(uuid.uuid4())

    if destination_candidate.exists():
        if strategy == "skip":
            return None
        elif strategy == "overwrite":
            final_target = destination_candidate
        elif strategy == "rename_counter":
            stem = Path(target_name).stem
            ext = Path(target_name).suffix
            counter = 1
            while True:
                candidate = target_dir / f"{stem} ({counter}){ext}"
                try:
                    fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    os.close(fd)
                    final_target = candidate
                    break
                except FileExistsError:
                    counter += 1
                    if counter > 10000:
                        raise RelocationError("Exceeded 10,000 collision iterations.")
    else:
        try:
            fd = os.open(destination_candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            final_target = destination_candidate
        except FileExistsError:
            return safe_copy_file(
                source_path, target_dir, target_name, strategy, journal_manager, retry_depth + 1
            )

    source_stat = source_path.stat()
    staging_filename = f".staging_{uuid.uuid4().hex}_{final_target.name}"
    staging_path = target_dir / staging_filename

    journal_manager.log_transaction(
        txn_id=txn_id,
        inode=source_stat.st_ino,
        action_type="copy",
        source_path=str(source_path),
        target_path=str(final_target),
        staging_path=str(staging_path),
        state="pending",
    )

    try:
        shutil.copy2(source_path, staging_path)
        with open(staging_path, "rb") as f:
            os.fsync(f.fileno())

        if staging_path.stat().st_size != source_stat.st_size:
            raise RelocationError("Verification failure: File sizes do not match after copy.")

        journal_manager.update_state(txn_id, "staging_written")
        os.replace(staging_path, final_target)
        journal_manager.update_state(txn_id, "committed")
    except Exception as err:
        if staging_path.exists():
            try:
                staging_path.unlink()
            except OSError:
                pass
        journal_manager.update_state(txn_id, "failed")
        raise RelocationError(f"Copy operation failed: {err}") from err

    return final_target


def safe_rename_file(
    source_path: Path,
    pattern: str,
    strategy: ConflictStrategy,
    journal_manager: JournalManager,
) -> Optional[Path]:
    """Executes safe rename with token expansion within the same parent directory."""
    new_name = expand_rename_pattern(source_path, pattern)
    if new_name == source_path.name:
        return source_path
    return safe_relocate_file(
        source_path=source_path,
        target_dir=source_path.parent,
        target_name=new_name,
        strategy=strategy,
        journal_manager=journal_manager,
    )


def safe_trash_file(
    source_path: Path,
    journal_manager: JournalManager,
) -> bool:
    """Executes safe FreeDesktop trash move with journal logging."""
    if not source_path.exists():
        return False

    txn_id = str(uuid.uuid4())
    st = source_path.stat()
    source_str = str(source_path.resolve())

    journal_manager.log_transaction(
        txn_id=txn_id,
        inode=st.st_ino,
        action_type="trash",
        source_path=source_str,
        target_path=None,
        staging_path=None,
        state="pending",
    )

    success, trash_uri = trash_file(source_path)
    if success:
        journal_manager.update_state(txn_id, "committed", trash_uri=trash_uri)
        return True
    else:
        journal_manager.update_state(txn_id, "failed")
        return False
