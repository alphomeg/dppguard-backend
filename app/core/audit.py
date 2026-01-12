import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlmodel import Session
from app.db.schema import SystemAuditLog, AuditAction

from app.db.core import engine


def _perform_audit_log(
    tenant_id: Optional[uuid.UUID],
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    action: AuditAction,
    changes: Dict[str, Any],
    ip_address: Optional[str] = None
):
    """
    Background worker.
    Creates its OWN session using the global engine.
    """
    try:
        # 2. OPEN A FRESH SESSION
        # Using 'with' ensures it commits/closes automatically
        # even if this background thread crashes.
        with Session(engine) as session:
            log_entry = SystemAuditLog(
                tenant_id=tenant_id,
                actor_user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                changes=changes,
                ip_address=ip_address,
                timestamp=datetime.utcnow()
            )
            session.add(log_entry)
            session.commit()
            # Session closes here automatically

    except Exception as e:
        # Log this failure to console/Sentry so you know if audits are failing
        print(f"AUDIT LOG FAILED: {e}")
