"""Load and validate problem.json — the pipeline's single source of truth."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 1
CHECKER_KINDS = ("stock", "custom")


class ProblemMetaError(ValueError):
    """problem.json is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Bound:
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True)
class Constraint:
    id: str
    expr: str
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True)
class Subtask:
    id: str
    points: int
    bounds: dict[str, Bound] = field(default_factory=dict)
    constraints_text: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Problem:
    name: str
    title: dict[str, str]
    tags: list[str]
    time_ms_published: int
    time_ms_computed: int | None
    memory_mb: int
    input: str
    output: str
    checker_kind: str
    checker_name: str
    constraints: list[Constraint]
    subtasks: list[Subtask]
    examples: list[dict]

    def constraint(self, cid: str) -> Constraint:
        for c in self.constraints:
            if c.id == cid:
                return c
        raise KeyError(cid)

    def subtask_ids(self) -> list[str]:
        return [s.id for s in self.subtasks]

    def effective_bound(self, subtask_id: str, constraint_id: str) -> Bound:
        """Global bound, narrowed by the subtask's override if it has one."""
        base = self.constraint(constraint_id)
        bound = Bound(base.min, base.max)
        for sub in self.subtasks:
            if sub.id != subtask_id:
                continue
            override = sub.bounds.get(constraint_id)
            if override is not None:
                bound = Bound(
                    override.min if override.min is not None else bound.min,
                    override.max if override.max is not None else bound.max,
                )
        return bound


def load(path: str | Path) -> Problem:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProblemMetaError(f"{path}: not valid JSON: {exc}") from exc

    if raw.get("schema") != SCHEMA:
        raise ProblemMetaError(
            f"{path}: unsupported schema {raw.get('schema')!r}, expected {SCHEMA}"
        )

    limits = raw.get("limits", {})
    io = raw.get("io", {})
    checker = raw.get("checker", {})

    if checker.get("kind") not in CHECKER_KINDS:
        raise ProblemMetaError(
            f"{path}: checker.kind is {checker.get('kind')!r}, "
            f"expected one of {CHECKER_KINDS}"
        )

    constraints = [
        Constraint(id=c["id"], expr=c["expr"], min=c.get("min"), max=c.get("max"))
        for c in raw.get("constraints", [])
    ]
    seen_c: set[str] = set()
    for c in constraints:
        if c.id in seen_c:
            raise ProblemMetaError(f"{path}: duplicate constraint id {c.id!r}")
        seen_c.add(c.id)

    subtasks = [
        Subtask(
            id=s["id"],
            points=s["points"],
            bounds={
                k: Bound(v.get("min"), v.get("max"))
                for k, v in s.get("bounds", {}).items()
            },
            constraints_text=list(s.get("constraints_text", [])),
            depends_on=list(s.get("depends_on", [])),
        )
        for s in raw.get("subtasks", [])
    ]

    seen_s: set[str] = set()
    for s in subtasks:
        if s.id in seen_s:
            raise ProblemMetaError(f"{path}: duplicate subtask id {s.id!r}")
        seen_s.add(s.id)

    total = sum(s.points for s in subtasks)
    if subtasks and total != 100:
        raise ProblemMetaError(f"{path}: subtask points sum to {total}, must be 100")

    for s in subtasks:
        for dep in s.depends_on:
            if dep not in seen_s:
                raise ProblemMetaError(
                    f"{path}: subtask {s.id!r} depends on unknown subtask {dep!r}"
                )
        for cid in s.bounds:
            if cid not in seen_c:
                raise ProblemMetaError(
                    f"{path}: subtask {s.id!r} bounds unknown constraint {cid!r}"
                )

    return Problem(
        name=raw["name"],
        title=raw.get("title", {}),
        tags=list(raw.get("tags", [])),
        time_ms_published=limits["time_ms_published"],
        time_ms_computed=limits.get("time_ms_computed"),
        memory_mb=limits["memory_mb"],
        input=io.get("input", "stdin"),
        output=io.get("output", "stdout"),
        checker_kind=checker["kind"],
        checker_name=checker["name"],
        constraints=constraints,
        subtasks=subtasks,
        examples=list(raw.get("examples", [])),
    )
