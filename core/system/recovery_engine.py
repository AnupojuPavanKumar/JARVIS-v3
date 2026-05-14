import logging
import os
import shutil
import time
from typing import Dict, Optional
from pydantic import BaseModel

log = logging.getLogger("RecoveryEngine")

class RecoverySnapshot(BaseModel):
    snapshot_id: str
    target_path: str
    snapshot_type: str # "file", "directory", "git"
    backup_path: Optional[str] = None
    created_at: float
    description: str

class FailureRecoverySystem:
    """
    Phase 5: Failure Recovery System
    Provides safe rollbacks for critical operations.
    """
    def __init__(self, backup_dir: str = "memory/backups"):
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)
        self.active_snapshots: Dict[str, RecoverySnapshot] = {}

    def create_directory_snapshot(self, target_path: str, description: str) -> Optional[str]:
        """Creates a full copy of a directory before risky operations (e.g. installs)."""
        if not os.path.exists(target_path) or not os.path.isdir(target_path):
            log.warning(f"[Recovery] Target directory {target_path} does not exist.")
            return None
            
        snapshot_id = f"snap_dir_{int(time.time()*1000)}"
        backup_path = os.path.join(self.backup_dir, snapshot_id)
        
        try:
            shutil.copytree(target_path, backup_path)
            snap = RecoverySnapshot(
                snapshot_id=snapshot_id,
                target_path=target_path,
                snapshot_type="directory",
                backup_path=backup_path,
                created_at=time.time(),
                description=description
            )
            self.active_snapshots[snapshot_id] = snap
            log.info(f"[Recovery] Created directory snapshot {snapshot_id} for {target_path}")
            return snapshot_id
        except Exception as e:
            log.error(f"[Recovery] Failed to create snapshot for {target_path}: {e}")
            return None

    def create_file_snapshot(self, target_path: str, description: str) -> Optional[str]:
        """Creates a backup of a single file."""
        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            return None
            
        snapshot_id = f"snap_file_{int(time.time()*1000)}"
        backup_path = os.path.join(self.backup_dir, snapshot_id)
        
        try:
            shutil.copy2(target_path, backup_path)
            snap = RecoverySnapshot(
                snapshot_id=snapshot_id,
                target_path=target_path,
                snapshot_type="file",
                backup_path=backup_path,
                created_at=time.time(),
                description=description
            )
            self.active_snapshots[snapshot_id] = snap
            log.info(f"[Recovery] Created file snapshot {snapshot_id} for {target_path}")
            return snapshot_id
        except Exception as e:
            log.error(f"[Recovery] Failed to create file snapshot for {target_path}: {e}")
            return None

    def rollback(self, snapshot_id: str) -> bool:
        """Restores the system to the state captured in the snapshot."""
        if snapshot_id not in self.active_snapshots:
            log.warning(f"[Recovery] Snapshot {snapshot_id} not found.")
            return False
            
        snap = self.active_snapshots[snapshot_id]
        
        try:
            if snap.snapshot_type == "directory":
                if os.path.exists(snap.target_path):
                    shutil.rmtree(snap.target_path)
                shutil.copytree(snap.backup_path, snap.target_path)
            elif snap.snapshot_type == "file":
                if os.path.exists(snap.backup_path):
                    shutil.copy2(snap.backup_path, snap.target_path)
            
            log.info(f"[Recovery] Rollback successful for {snap.target_path} using {snapshot_id}")
            self.discard_snapshot(snapshot_id)
            return True
        except Exception as e:
            log.error(f"[Recovery] Rollback failed for {snapshot_id}: {e}")
            return False

    def discard_snapshot(self, snapshot_id: str):
        """Cleans up backup files for successful operations."""
        if snapshot_id in self.active_snapshots:
            snap = self.active_snapshots[snapshot_id]
            try:
                if snap.backup_path and os.path.exists(snap.backup_path):
                    if os.path.isdir(snap.backup_path):
                        shutil.rmtree(snap.backup_path)
                    else:
                        os.remove(snap.backup_path)
                del self.active_snapshots[snapshot_id]
            except Exception as e:
                log.warning(f"[Recovery] Cleanup failed for {snapshot_id}: {e}")

# ── Singleton ──────────────────────────────────────────────────────────────────
_recovery_engine_instance: Optional[FailureRecoverySystem] = None

def get_recovery_engine() -> FailureRecoverySystem:
    global _recovery_engine_instance
    if _recovery_engine_instance is None:
        _recovery_engine_instance = FailureRecoverySystem()
    return _recovery_engine_instance
