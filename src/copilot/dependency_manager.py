"""
Action Dependency Manager for Task M7-08 Action Planning.
Module 07: AI Copilot & Merchant Workspace

Manages task dependencies and blocks circular dependency graphs.
"""

from typing import List, Dict, Any, Set


class CircularDependencyError(Exception):
    pass


class ActionDependencyManager:
    """Validates and manages operational task dependency graphs."""

    @classmethod
    def validate_dependencies(cls, tasks: List[Dict[str, Any]]) -> bool:
        """Detects circular dependency cycles in task graph."""
        task_map = {t["task_id"]: t.get("depends_on", []) for t in tasks}

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def is_cyclic(task_id: str) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            for dep in task_map.get(task_id, []):
                if dep not in visited:
                    if is_cyclic(dep):
                        return True
                elif dep in rec_stack:
                    return True

            rec_stack.remove(task_id)
            return False

        for t in tasks:
            tid = t["task_id"]
            if tid not in visited:
                if is_cyclic(tid):
                    raise CircularDependencyError(f"Circular dependency cycle detected starting at task '{tid}'")

        return True

    @classmethod
    def resolve_task_statuses(cls, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sets task status to BLOCKED if any prerequisite tasks are not COMPLETED."""
        completed_ids = {t["task_id"] for t in tasks if t.get("status") == "COMPLETED"}

        for t in tasks:
            deps = set(t.get("depends_on", []))
            if t.get("status") in ["COMPLETED", "CANCELLED", "IN_PROGRESS"]:
                continue
            if deps and not deps.issubset(completed_ids):
                t["status"] = "BLOCKED"
            else:
                t["status"] = "PENDING"

        return tasks
