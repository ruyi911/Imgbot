from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BindingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    UNBOUND = "UNBOUND"


class ReplyStatus(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BotInstance(Base):
    __tablename__ = "bot_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    bot_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_username: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GroupBinding(Base):
    __tablename__ = "group_bindings"
    __table_args__ = (
        Index(
            "uq_group_bindings_active_instance",
            "bot_instance_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "uq_group_bindings_active_chat",
            "chat_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_title: Mapped[str] = mapped_column(String(255), nullable=False)
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[BindingStatus] = mapped_column(
        Enum(BindingStatus, native_enum=False), nullable=False, default=BindingStatus.ACTIVE
    )
    bound_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unbound_by: Mapped[int | None] = mapped_column(BigInteger)
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    instance: Mapped[BotInstance] = relationship()


class Administrator(Base):
    __tablename__ = "administrators"
    __table_args__ = (
        UniqueConstraint("bot_instance_id", "telegram_user_id", name="uq_admin_instance_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReplyTemplate(Base):
    __tablename__ = "reply_templates"
    __table_args__ = (UniqueConstraint("bot_instance_id", name="uq_template_instance"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TemplateButton(Base):
    __tablename__ = "template_buttons"
    __table_args__ = (
        UniqueConstraint("bot_instance_id", "row_number", "column_number", name="uq_button_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    text: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_number: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StartPage(Base):
    __tablename__ = "start_pages"
    __table_args__ = (UniqueConstraint("bot_instance_id", name="uq_start_page_instance"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StartPageButton(Base):
    __tablename__ = "start_page_buttons"
    __table_args__ = (
        UniqueConstraint(
            "bot_instance_id", "row_number", "column_number", name="uq_start_button_slot"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    text: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_number: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint(
            "bot_instance_id", "chat_id", "submission_key", name="uq_submission_key"
        ),
        Index("ix_submissions_sent_at", "bot_instance_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    group_binding_id: Mapped[int] = mapped_column(ForeignKey("group_bindings.id"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_title: Mapped[str] = mapped_column(String(255), nullable=False)
    submission_key: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_group_id: Mapped[str | None] = mapped_column(String(128))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    first_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    last_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    display_name_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    username_snapshot: Mapped[str | None] = mapped_column(String(64))
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reply_not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reply_status: Mapped[ReplyStatus] = mapped_column(
        Enum(ReplyStatus, native_enum=False), nullable=False, default=ReplyStatus.PENDING
    )
    reply_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_message_id: Mapped[int | None] = mapped_column(BigInteger)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_error: Mapped[str | None] = mapped_column(Text)
    template_version: Mapped[int | None] = mapped_column(Integer)

    parts: Mapped[list[SubmissionPart]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class SubmissionPart(Base):
    __tablename__ = "submission_parts"
    __table_args__ = (
        UniqueConstraint("bot_instance_id", "chat_id", "message_id", name="uq_message_part"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="parts")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_instance_created", "bot_instance_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
