"""Glucose readings (TimescaleDB hypertable, Section 18.2).

The table, hypertable conversion, continuous aggregates, and columnstore policy are
created by Alembic migration 0001 with raw SQL; this model is for ORM reads/writes only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from sugarscout.db import Base


class GlucoseReading(Base):
    __tablename__ = "glucose_readings"
    __table_args__ = (
        CheckConstraint("value_mg_dl BETWEEN 20 AND 600", name="glucose_readings_value_range"),
    )

    # Primary key includes the time column, as hypertables require (Section 18.2).
    # Phase 2 adds the foreign key to children(id).
    child_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value_mg_dl: Mapped[int] = mapped_column(Integer, nullable=False)
    trend: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
