"""
Entity Tracker for Task M7-09 Conversation & Memory.
Module 07: AI Copilot & Merchant Workspace

Tracks active entities (SKU, Decision ID, Action Plan ID) across multi-turn chat sessions.
"""

import re
from typing import Dict, Any, List, Optional


class EntityTracker:
    """Tracks entity mentions and maintains active focus within a conversation session."""

    SKU_PATTERN = re.compile(r'(SKU[-_][A-Za-z0-9_-]+|SKU[0-9]+)', re.IGNORECASE)
    DECISION_PATTERN = re.compile(r'(DEC[-_][A-Za-z0-9_-]+)', re.IGNORECASE)
    PLAN_PATTERN = re.compile(r'(PLAN[-_][A-Za-z0-9_-]+)', re.IGNORECASE)

    def __init__(self):
        self.tracked_entities: Dict[str, Dict[str, Any]] = {}

    def extract_and_update(self, text: str) -> Dict[str, Any]:
        sku_m = self.SKU_PATTERN.search(text)
        dec_m = self.DECISION_PATTERN.search(text)
        plan_m = self.PLAN_PATTERN.search(text)

        if sku_m:
            sku_id = sku_m.group(1).upper()
            self.tracked_entities["SKU"] = {"id": sku_id, "type": "SKU"}

        if dec_m:
            dec_id = dec_m.group(1).upper()
            self.tracked_entities["DECISION"] = {"id": dec_id, "type": "DECISION"}

        if plan_m:
            plan_id = plan_m.group(1).upper()
            self.tracked_entities["ACTION_PLAN"] = {"id": plan_id, "type": "ACTION_PLAN"}

        active_sku = self.tracked_entities.get("SKU", {}).get("id")
        active_dec = self.tracked_entities.get("DECISION", {}).get("id")
        active_plan = self.tracked_entities.get("ACTION_PLAN", {}).get("id")

        return {
            "active_sku": active_sku,
            "active_decision_id": active_dec,
            "active_plan_id": active_plan,
            "all_entities": list(self.tracked_entities.values())
        }
