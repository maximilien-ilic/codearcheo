"""Serializable facts extracted from syntax trees, independent of CLI and AI clients."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Symbol(BaseModel):
    name: str
    qualified_name: str
    kind: str
    path: str
    line: int
    end_line: int


class Reference(BaseModel):
    name: str
    path: str
    line: int


class Import(BaseModel):
    module: str
    line: int
    names: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)


class Module(BaseModel):
    path: str
    language: str
    symbols: list[Symbol] = Field(default_factory=list)
    imports: list[Import] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)
    entry_point: bool = False
    syntax_errors: bool = False


class ModuleRank(BaseModel):
    path: str
    incoming: int
    outgoing: int
    churn: int = 0
    risk_score: int = 0


class CodeSummary(BaseModel):
    modules: int
    symbols: int
    internal_edges: int
    central_modules: list[ModuleRank]
    entry_points: list[str]
    risky_modules: list[ModuleRank]
    skipped: dict[str, str] = Field(default_factory=dict)
    limitations: str = (
        "Static imports only. Dynamic imports, build conditions and custom module aliases "
        "may be unresolved; identifier usages are lexical candidates, not binding analysis."
    )
