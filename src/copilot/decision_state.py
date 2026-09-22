"""
Decision State Tracker for Task M7-07 Decision Copilot.
Module 07: AI Copilot & Merchant Workspace

Manages decision lifecycle states: RECOMMENDED -> SIMULATED -> SELECTED -> CONFIRMED -> EXECUTED.
"""

from enum import Enum


class DecisionState(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    SIMULATED = "SIMULATED"
    SELECTED = "SELECTED"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
