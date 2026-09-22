"""
Dependency Resolver for Task M7-04 Tool Orchestration.
Module 07: AI Copilot & Merchant Workspace

Resolves prerequisites and orders tool execution steps (e.g. Risk -> Capital -> Decision).
"""

from typing import List, Dict, Any, Set


class DependencyResolver:
    """Resolves data dependencies between DSS tools."""

    PREREQUISITES_MAP = {
        "get_risk_profile": [],
        "get_risk_explanation": ["get_risk_profile"],
        "get_capital_exposure": [],
        "get_inventory_aging": [],
        "get_recovery_options": ["get_risk_profile", "get_capital_exposure"],
        "get_decision_recommendation": ["get_risk_profile", "get_capital_exposure", "get_inventory_aging"],
        "get_priority_actions": ["get_risk_profile", "get_capital_exposure", "get_decision_recommendation"],
        "get_dataset_status": []
    }

    @classmethod
    def resolve_dependencies(cls, tools: List[str]) -> List[str]:
        """Returns topological ordering of tools to satisfy all prerequisites."""
        resolved: List[str] = []
        visited: Set[str] = set()

        def visit(tool: str):
            if tool in visited:
                return
            prereqs = cls.PREREQUISITES_MAP.get(tool, [])
            for p in prereqs:
                if p in tools:
                    visit(p)
            visited.add(tool)
            resolved.append(tool)

        for t in tools:
            visit(t)

        return resolved

    @classmethod
    def get_parallel_batches(cls, resolved_tools: List[str]) -> List[List[str]]:
        """Groups resolved tools into parallel execution batches."""
        batches: List[List[str]] = []
        executed: Set[str] = set()

        remaining = list(resolved_tools)
        while remaining:
            current_batch = []
            for t in list(remaining):
                prereqs = set(cls.PREREQUISITES_MAP.get(t, []))
                # Tool can run if all its prerequisites in the query have already executed
                if prereqs.issubset(executed):
                    current_batch.append(t)

            if not current_batch:
                # Fallback to prevent infinite loop
                current_batch = [remaining[0]]

            batches.append(current_batch)
            for t in current_batch:
                executed.add(t)
                remaining.remove(t)

        return batches
