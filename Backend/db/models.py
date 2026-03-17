"""SQLAlchemy ORM models for Frontier AI Radar (PostgreSQL / ai_radar schema)."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    Float,
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class User(Base):
    """Subscribed users who receive digest emails (and optional login credentials)."""

    __tablename__ = "users"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    name              = Column(String(200), nullable=False)
    email             = Column(String(320), nullable=False, unique=True)
    password_hash     = Column(String(256), nullable=True)
    is_admin          = Column(Boolean, default=False, nullable=False)
    centific_team     = Column(String(100), nullable=True)
    active_persona_id = Column(PG_UUID(as_uuid=True), nullable=True)
    subscribed_at     = Column(DateTime(timezone=False), default=lambda: datetime.now(timezone.utc))

    # Relationships
    runs        = relationship("Run", back_populates="user")
    competitors = relationship("Competitor", back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} name={self.name} email={self.email}>"


class Extraction(Base):
    """Stores basic information before passing it to the next stages."""

    __tablename__ = "extractions"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    publication_date = Column(DateTime(timezone=False), nullable=True)
    mode             = Column(String(10), CheckConstraint("mode IN ('job', 'UI')"), nullable=True)
    metadata_        = Column("metadata", Text, nullable=True)  # JSON stored as TEXT
    created_at       = Column(DateTime(timezone=False), default=lambda: datetime.now(timezone.utc))

    # Relationships
    findings = relationship("Finding", back_populates="extraction", cascade="all, delete-orphan")
    runs     = relationship("Run", back_populates="extraction")

    def __repr__(self) -> str:
        return f"<Extraction id={self.id} mode={self.mode} created_at={self.created_at}>"


class Run(Base):
    """Tracks history, status, and performance of each system execution."""

    __tablename__ = "runs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id", ondelete="SET NULL"), nullable=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status        = Column(String(20), nullable=True)  # running, success, failure, partial_failure
    run_mode      = Column(String(20), default="daily")
    time_taken    = Column(Integer, nullable=True)     # duration in seconds
    started_at    = Column(DateTime(timezone=False), default=lambda: datetime.now(timezone.utc))
    completed_at  = Column(DateTime(timezone=False), nullable=True)
    pdf_path      = Column(Text, nullable=True)
    persona_id    = Column(PG_UUID(as_uuid=True), nullable=True)
    config        = Column(JSONB, default=dict)
    # Azure Blob Storage — paths inside the container
    blob_pdf_path           = Column(Text, nullable=True)  # Frontier-AI-Radar/digest-.../digest.pdf
    blob_audio_path         = Column(Text, nullable=True)  # deprecated — kept for backwards compat
    audio_script_blob_path  = Column(Text, nullable=True)  # LLM narration .txt in blob
    active_flag             = Column(String(1), default="Y", nullable=False)

    # Relationships
    extraction = relationship("Extraction", back_populates="runs")
    user       = relationship("User", back_populates="runs")
    resources  = relationship("Resource", back_populates="run", cascade="all, delete-orphan")
    findings   = relationship("Finding", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Run id={self.id} status={self.status} time_taken={self.time_taken}s>"


class RunAudioPreset(Base):
    """Per-run record of which voice presets have been generated and their blob paths.

    Replaces runs.audio_presets_paths JSONB — one row per (run_id, preset_id).
    Permanent record; never deleted when SAS expires.
    """

    __tablename__ = "run_audio_presets"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    run_id       = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    preset_id    = Column(String(50), nullable=False)   # e.g. "rachel_professional"
    blob_path    = Column(Text, nullable=True)           # blob or local path to MP3
    is_ready     = Column(Boolean, default=False, nullable=False)
    generated_at = Column(DateTime(timezone=False), nullable=True)

    def __repr__(self) -> str:
        return f"<RunAudioPreset run={self.run_id} preset={self.preset_id} ready={self.is_ready}>"


class RunAssetCache(Base):
    """Short-lived SAS URL cache per (run_id, asset_type, preset_id).

    Replaces runs.blob_sas_cache JSONB.
    Rows are upserted on every SAS regeneration; expire independently per preset.
    asset_type: 'pdf' | 'audio'
    preset_id:  voice preset id for audio assets, NULL for pdf
    """

    __tablename__ = "run_asset_cache"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    run_id     = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    asset_type = Column(String(50), nullable=False)
    preset_id  = Column(String(50), nullable=True)
    sas_url    = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=False), nullable=False)

    def __repr__(self) -> str:
        return f"<RunAssetCache run={self.run_id} type={self.asset_type} preset={self.preset_id}>"


class VoicePreset(Base):
    """ElevenLabs voice preset catalog (seeded via SQL, managed in DB)."""

    __tablename__ = "voice_presets"

    id               = Column(String(50),  primary_key=True)  # "rachel_professional"
    voice_id         = Column(String(100), nullable=False)    # ElevenLabs voice ID
    label            = Column(String(100), nullable=False)    # "Rachel – Female, Professional"
    gender           = Column(String(20),  nullable=False, default="neutral")
    style            = Column(String(50),  nullable=False, default="professional")
    elevenlabs_model = Column(String(100), nullable=False, default="eleven_turbo_v2")
    is_active        = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<VoicePreset id={self.id} label={self.label}>"


class Finding(Base):
    """Stores high-impact summaries, scores, and content generated by agents."""

    __tablename__ = "findings"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    extraction_id      = Column(Integer, ForeignKey("extractions.id", ondelete="CASCADE"), nullable=True)
    run_id             = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=True)
    agent_name         = Column(String(30), nullable=False)  # research, competitor, model, benchmark
    title              = Column(String(500), nullable=True)
    source_url         = Column(Text, nullable=True)
    publisher          = Column(String(200), nullable=True)
    what_changed       = Column(Text, nullable=True)
    why_it_matters     = Column(Text, nullable=True)
    evidence           = Column(Text, nullable=True)
    confidence         = Column(String(10), default="MEDIUM")
    impact_score       = Column(Float, default=0.0)
    relevance          = Column(Float, default=0.0)
    novelty            = Column(Float, default=0.0)
    credibility        = Column(Float, default=0.0)
    actionability      = Column(Float, default=0.0)
    rank               = Column(Integer, nullable=True)
    topic_cluster      = Column(String(50), nullable=True)
    needs_verification = Column(Boolean, default=False)
    tags               = Column(ARRAY(Text), nullable=True)
    html_content       = Column(Text, nullable=True)
    metadata_          = Column("metadata", JSONB, default=dict)  # extra/overflow data
    created_at         = Column(DateTime(timezone=False), default=lambda: datetime.now(timezone.utc))

    # Relationships
    extraction = relationship("Extraction", back_populates="findings")
    run        = relationship("Run", back_populates="findings")

    def __repr__(self) -> str:
        return f"<Finding id={self.id} agent={self.agent_name} title={str(self.title)[:40]}>"


class Resource(Base):
    """Tracks every source URL / name discovered by each agent per run."""

    __tablename__ = "resources"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    run_id        = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    agent_name    = Column(String(20), nullable=False)
    name          = Column(String(500), nullable=False)
    url           = Column(Text, nullable=True)
    resource_type = Column(String(50), nullable=True)
    discovered_at = Column(DateTime(timezone=False), default=lambda: datetime.now(timezone.utc))

    # Relationships
    run = relationship("Run", back_populates="resources")

    def __repr__(self) -> str:
        return f"<Resource id={self.id} agent={self.agent_name} name={self.name[:40]}>"


class Competitor(Base):
    """Competitor source URLs used by the Competitor Intelligence Agent."""

    __tablename__ = "competitors"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(200), nullable=False)
    url         = Column(Text, nullable=False, unique=True)
    source_type = Column(String(20), nullable=False)  # "rss" | "webpage"
    selector    = Column(String(200), nullable=True)  # CSS selector for webpage type
    is_default  = Column(Boolean, default=True)
    is_active   = Column(Boolean, default=True)
    added_by    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=False), default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="competitors")

    def __repr__(self) -> str:
        return f"<Competitor id={self.id} name={self.name} active={self.is_active}>"
