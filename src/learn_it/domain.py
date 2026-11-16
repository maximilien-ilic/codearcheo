"""Data model shared by every layer. Pydantic validates it and (de)serializes it as JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Commit(BaseModel):
    sha: str
    author: str
    date: datetime
    subject: str
    files: list[str] = Field(default_factory=list, exclude=True)  # only used to find hotspots


class Technology(BaseModel):
    """A technology the project depends on, found in a manifest or a config file."""

    name: str
    # language | framework | ui | data | api | ai | infra | ci | testing | tooling | library
    category: str
    source: str  # file where it was detected: the first piece of evidence
    adopted: Commit | None = None  # oldest commit that introduced it
    # Text searched in the history of `source` to date the adoption (None: the file's creation).
    needle: str | None = Field(default=None, exclude=True)


class Hotspot(BaseModel):
    path: str
    commits: int


class ProjectProfile(BaseModel):
    """Deterministic facts gathered by `learn-it scan`, before any LLM call."""

    name: str
    origin: str | None = None
    head: str | None = None
    files: int
    languages: dict[str, int]
    technologies: list[Technology]
    docs: list[str]
    commits: int = 0
    contributors: int = 0
    first_commit: datetime | None = None
    last_commit: datetime | None = None
    hotspots: list[Hotspot] = []
    recent_commits: list[Commit] = []
    uncommitted: list[str] = []


class Decision(BaseModel):
    """A technical decision reconstructed from the code and its history, shaped like an ADR."""

    title: str = Field(description="Short name, e.g. 'PostgreSQL as the main datastore'.")
    category: Literal[
        "architecture", "language", "framework", "data", "api",
        "infra", "testing", "security", "tooling", "process",
    ]
    context: str = Field(description="The problem and the forces at play when it was decided.")
    decision: str = Field(description="What was decided, concretely, as seen in the code.")
    rationale: str = Field(
        description="Why. Quote the source when documented; otherwise explain the inference."
    )
    rationale_source: Literal["documented", "inferred"] = Field(
        description="'documented' only when a commit, doc or comment states the reason."
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="Options visibly considered or replaced, e.g. a dependency removed by the "
        "same commit.",
    )
    consequences: list[str] = Field(
        description="Positive and negative effects visible in today's code."
    )
    introduced_in: str | None = Field(
        default=None, description="Sha of the commit that introduced it, when found."
    )
    evidence: list[str] = Field(
        description="References backing this record, `path:lines` or `commit <sha>`, each "
        "followed by what it shows."
    )


class Recommendation(BaseModel):
    """A review item that can be sorted, exported and explicitly published as an issue."""

    title: str = Field(min_length=1)
    decision: str = Field(min_length=1, description="Decision being reviewed.")
    verdict: Literal["keep", "improve", "replace"]
    reasons: list[str] = Field(min_length=1)
    proposal: str = ""
    tradeoffs: list[str] = Field(default_factory=list)
    effort: Literal["S", "M", "L"]
    impact: Literal["low", "medium", "high"]
    first_steps: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(min_length=1)
