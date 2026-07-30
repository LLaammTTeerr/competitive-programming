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


def _type_name(value) -> str:
    """JSON's name for a Python value's type, so the message a hand-editor
    reads matches the document they are editing."""
    return {type(None): "null", bool: "boolean", int: "number",
            float: "number", str: "string", list: "array",
            dict: "object"}.get(type(value), type(value).__name__)


def _object(value, path: Path, what: str) -> dict:
    """`value` as a JSON object, or `ProblemMetaError` naming what was found.

    Standing ruling R1 in one place: `problem.json` is hand-authored and is
    the pipeline's source of truth, so every way it can be *wrong* has to
    arrive as a `ProblemMetaError` naming the field. Missing keys were
    already wrapped; wrong *types* were not, and `"limits": null` — an
    ordinary typo — surfaced as `TypeError: 'NoneType' object is not
    subscriptable` from somewhere far below the reader's document.
    """
    if value is None:
        raise ProblemMetaError(
            f"{path}: {what} is null; expected an object (did a key get "
            "emptied rather than removed?)")
    if not isinstance(value, dict):
        raise ProblemMetaError(
            f"{path}: {what} is a JSON {_type_name(value)}, expected an object")
    return value


def _array(value, path: Path, what: str) -> list:
    """`value` as a JSON array, or `ProblemMetaError` naming what was found."""
    if value is None:
        raise ProblemMetaError(
            f"{path}: {what} is null; expected an array")
    if not isinstance(value, list):
        raise ProblemMetaError(
            f"{path}: {what} is a JSON {_type_name(value)}, expected an array")
    return value


def _integer(value, path: Path, what: str, *, allow_none: bool = False):
    """`value` as a Python int, or `ProblemMetaError` naming what was found.

    Non-integer bounds are rejected rather than coerced, and that is the
    whole point of this function. `gen_constraints_header.py` f-strings a
    bound straight into `static const long long NAME = <value>;`, so
    `"max": 2.9` emits `= 2.9;`, which C++ **silently truncates to 2** — and
    a probability bound `"max": 0.5` becomes `0`, after which the generated
    header makes the validator reject every legal test. That header exists
    precisely to make validator/`problem.json` drift impossible; a float
    bound is a path where they drift silently, so it must not load at all.

    `"points": "100"` is the same class from the other direction: it summed
    with `+` into a `TypeError` deep inside the points check rather than a
    message about the subtask that has it.

    `bool` is excluded deliberately: it is an `int` subclass in Python, so
    `"max": true` would otherwise load as 1.
    """
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProblemMetaError(
            f"{path}: {what} is {value!r} (JSON {_type_name(value)}), "
            "expected an integer. Bounds are emitted verbatim into "
            "files/constraints.h as `static const long long`, where a "
            "non-integer is silently truncated by the C++ compiler — 2.9 "
            "becomes 2 and 0.5 becomes 0.")
    return value


def load(path: str | Path) -> Problem:
    """Load and validate `problem.json`, raising `ProblemMetaError` for
    every way it can be wrong — missing, unreadable, not JSON, the wrong
    shape, or internally inconsistent."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProblemMetaError(f"{path}: no such file") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ProblemMetaError(f"{path}: cannot be read: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProblemMetaError(f"{path}: not valid JSON: {exc}") from exc

    raw = _object(raw, path, "the top level of the document")

    if raw.get("schema") != SCHEMA:
        raise ProblemMetaError(
            f"{path}: unsupported schema {raw.get('schema')!r}, expected {SCHEMA}"
        )

    limits = _object(raw.get("limits", {}), path, "'limits'")
    io = _object(raw.get("io", {}), path, "'io'")
    checker = _object(raw.get("checker", {}), path, "'checker'")

    if checker.get("kind") not in CHECKER_KINDS:
        raise ProblemMetaError(
            f"{path}: checker.kind is {checker.get('kind')!r}, "
            f"expected one of {CHECKER_KINDS}"
        )

    constraints = []
    for i, c in enumerate(_array(raw.get("constraints", []), path, "'constraints'")):
        c = _object(c, path, f"constraints[{i}]")
        try:
            cid, expr = c["id"], c["expr"]
        except KeyError as exc:
            raise ProblemMetaError(
                f"{path}: constraint missing required field {exc}"
            ) from exc
        constraints.append(Constraint(
            id=cid, expr=expr,
            min=_integer(c.get("min"), path, f"constraint {cid!r} min",
                         allow_none=True),
            max=_integer(c.get("max"), path, f"constraint {cid!r} max",
                         allow_none=True),
        ))

    seen_c: set[str] = set()
    for c in constraints:
        if c.id in seen_c:
            raise ProblemMetaError(f"{path}: duplicate constraint id {c.id!r}")
        seen_c.add(c.id)

    subtasks = []
    for i, s in enumerate(_array(raw.get("subtasks", []), path, "'subtasks'")):
        s = _object(s, path, f"subtasks[{i}]")
        try:
            sid, points = s["id"], s["points"]
        except KeyError as exc:
            raise ProblemMetaError(
                f"{path}: subtask missing required field {exc}"
            ) from exc
        # `except KeyError` around this comprehension could never have
        # caught the bounds case: a non-object bound raises AttributeError
        # from `.get`, not KeyError.
        bounds = {}
        for k, v in _object(s.get("bounds", {}), path,
                            f"subtask {sid!r} 'bounds'").items():
            v = _object(v, path, f"subtask {sid!r} bound {k!r}")
            bounds[k] = Bound(
                _integer(v.get("min"), path, f"subtask {sid!r} bound {k!r} min",
                         allow_none=True),
                _integer(v.get("max"), path, f"subtask {sid!r} bound {k!r} max",
                         allow_none=True),
            )
        subtasks.append(Subtask(
            id=sid,
            points=_integer(points, path, f"subtask {sid!r} points"),
            bounds=bounds,
            constraints_text=list(_array(s.get("constraints_text", []), path,
                                         f"subtask {sid!r} 'constraints_text'")),
            depends_on=list(_array(s.get("depends_on", []), path,
                                   f"subtask {sid!r} 'depends_on'")),
        ))

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

    order: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(sid: str, trail: list[str]) -> None:
        if sid in order:
            return
        if sid in visiting:
            loop = trail[trail.index(sid):] + [sid]
            raise ProblemMetaError(
                f"{path}: subtask dependency cycle: {' -> '.join(loop)}"
            )
        visiting.add(sid)
        for dep in next(s for s in subtasks if s.id == sid).depends_on:
            visit(dep, trail + [sid])
        visiting.discard(sid)
        order[sid] = len(order)

    for s in subtasks:
        visit(s.id, [])

    try:
        name = raw["name"]
    except KeyError as exc:
        raise ProblemMetaError(f"{path}: missing required field {exc}") from exc

    try:
        time_ms_published = limits["time_ms_published"]
        memory_mb = limits["memory_mb"]
    except KeyError as exc:
        raise ProblemMetaError(f"{path}: missing required field in limits {exc}") from exc
    time_ms_published = _integer(time_ms_published, path,
                                 "limits.time_ms_published")
    memory_mb = _integer(memory_mb, path, "limits.memory_mb")

    try:
        checker_kind = checker["kind"]
        checker_name = checker["name"]
    except KeyError as exc:
        raise ProblemMetaError(f"{path}: missing required field in checker {exc}") from exc

    return Problem(
        name=name,
        title=_object(raw.get("title", {}), path, "'title'"),
        tags=list(_array(raw.get("tags", []), path, "'tags'")),
        time_ms_published=time_ms_published,
        time_ms_computed=_integer(limits.get("time_ms_computed"), path,
                                  "limits.time_ms_computed", allow_none=True),
        memory_mb=memory_mb,
        input=io.get("input", "stdin"),
        output=io.get("output", "stdout"),
        checker_kind=checker_kind,
        checker_name=checker_name,
        constraints=constraints,
        subtasks=subtasks,
        examples=list(_array(raw.get("examples", []), path, "'examples'")),
    )
