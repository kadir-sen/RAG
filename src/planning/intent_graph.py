"""Subtask dependency graph (Sprint C).

A compound plan is a DAG: each subtask may depend on earlier subtasks' outputs.
This module orders subtasks so every dependency runs before its dependents, and
rejects cycles / dangling references. Pure and deterministic — stable order for
independent nodes (declaration order) so plans are reproducible.
"""

from __future__ import annotations

from typing import List, Tuple

from .schemas import SubTask


class PlanGraphError(ValueError):
    pass


def validate_edges(subtasks: List[SubTask]) -> List[str]:
    """Return a list of edge problems (dangling depends_on / duplicate ids)."""
    problems: List[str] = []
    ids = [s.id for s in subtasks]
    seen = set()
    for sid in ids:
        if sid in seen:
            problems.append(f"duplicate subtask id '{sid}'")
        seen.add(sid)
    idset = set(ids)
    for s in subtasks:
        for dep in s.depends_on:
            if dep not in idset:
                problems.append(f"subtask '{s.id}' depends on unknown '{dep}'")
            if dep == s.id:
                problems.append(f"subtask '{s.id}' depends on itself")
    return problems


def topo_order(subtasks: List[SubTask]) -> List[SubTask]:
    """Kahn's algorithm; stable in declaration order among ready nodes.

    Raises PlanGraphError on a dangling reference or a cycle."""
    problems = validate_edges(subtasks)
    if problems:
        raise PlanGraphError("; ".join(problems))

    by_id = {s.id: s for s in subtasks}
    indeg = {s.id: 0 for s in subtasks}
    for s in subtasks:
        for _ in s.depends_on:
            indeg[s.id] += 1

    order: List[SubTask] = []
    # Preserve declaration order among ready nodes for reproducibility.
    ready = [s.id for s in subtasks if indeg[s.id] == 0]
    while ready:
        sid = ready.pop(0)
        order.append(by_id[sid])
        for s in subtasks:
            if sid in s.depends_on:
                indeg[s.id] -= 1
                if indeg[s.id] == 0:
                    ready.append(s.id)
        # keep ready in declaration order
        ready.sort(key=lambda x: [t.id for t in subtasks].index(x))

    if len(order) != len(subtasks):
        remaining = [s.id for s in subtasks if s not in order]
        raise PlanGraphError(f"cycle among subtasks: {remaining}")
    return order
