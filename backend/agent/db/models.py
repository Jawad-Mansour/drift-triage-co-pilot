import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.agent.db.base import Base


class InvestigationStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_HIL = "awaiting_hil"
    COMPLETED = "completed"
    FAILED = "failed"


class HILStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DriftInvestigation(Base):
    """One row per incoming drift webhook event."""

    __tablename__ = "drift_investigations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    feature_name: Mapped[str] = mapped_column(String(255), nullable=False)
    psi_score: Mapped[float | None] = mapped_column(nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    drift_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    proposed_action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comms_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[InvestigationStatus] = mapped_column(
        SAEnum(
            InvestigationStatus,
            name="investigation_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=InvestigationStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    hil_approvals: Mapped[list["HILApproval"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="HILApproval.created_at",
    )
    action_logs: Mapped[list["ActionLog"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="ActionLog.created_at",
    )

    __table_args__ = (
        Index("ix_drift_investigations_status", "status"),
        Index("ix_drift_investigations_feature", "feature_name"),
    )


class HILApproval(Base):
    """Pending or resolved human-in-the-loop request. Expires after approval_timeout_minutes."""

    __tablename__ = "hil_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drift_investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[HILStatus] = mapped_column(
        SAEnum(HILStatus, name="hil_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=HILStatus.PENDING,
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    investigation: Mapped["DriftInvestigation"] = relationship(back_populates="hil_approvals")

    __table_args__ = (
        Index("ix_hil_approvals_thread_id", "thread_id"),
        Index("ix_hil_approvals_status", "status"),
    )


class IdempotencyKey(Base):
    """Dedup store. Key = hash(action+feature+hour+severity). TTL enforced in app layer."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (Index("ix_idempotency_keys_expires_at", "expires_at"),)


class ActionLog(Base):
    """Append-only audit trail of every action the agent executed."""

    __tablename__ = "action_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drift_investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    worker_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    investigation: Mapped["DriftInvestigation"] = relationship(back_populates="action_logs")

    __table_args__ = (
        Index("ix_action_log_thread_id", "thread_id"),
        Index("ix_action_log_action_type", "action_type"),
    )
