"""
Test suite for Task M7-03 Intent Classification (Module 07).
Verifies AC-01 through AC-12 requirements:
- Intent Taxonomy & Intent Classification mapping
- Entity Extraction (SKU ID, category, risk class, top_n)
- Multi-Turn Context Resolution & SKU inheritance
- Confidence Score, Ambiguity Handling & Clarification Prompt
- Multi-Intent Compound Query detection
- Scope Guard Out-of-Scope Blocking
- Intent-to-Context Requirements mapping & Traceability Audit
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.intent_classifier import IntentClassifier
from src.copilot.entity_extractor import EntityExtractor
from src.copilot.context_resolver import ContextResolver
from src.copilot.scope_guard import ScopeGuard
from src.copilot.intent_validator import IntentValidator


class TestIntentClassification(TestCase):

    def setUp(self):
        self.classifier = IntentClassifier()
        self.resolver = ContextResolver()

    def test_intent_classification_taxonomy(self):
        """AC-01, AC-02, AC-05, AC-08, AC-11: Verifies classification into taxonomy codes & context mapping."""
        # Risk query
        res1 = self.classifier.classify("Cho tôi biết các SKU rủi ro bán chậm", session_id="s1")
        self.assertEqual(res1["primary_intent"], "RISK_QUERY")
        self.assertIn("RISK_PROFILE", res1["context_requirements"])
        self.assertGreater(res1["confidence"], 0.70)
        self.assertIn("classification_id", res1)

        # Decision query
        res2 = self.classifier.classify("Tôi nên xử lý SKU-001 như thế nào?", session_id="s1")
        self.assertEqual(res2["primary_intent"], "DECISION_QUERY")
        self.assertIn("DECISION_RECOMMENDATION", res2["context_requirements"])

    def test_entity_extraction(self):
        """AC-03: Verifies extraction of SKU ID, risk class, top_n, and category entities."""
        entities = EntityExtractor.extract_entities("Cho tôi 10 SKU Critical thuộc nhóm Thời trang")
        self.assertEqual(entities["risk_class"], "CRITICAL")
        self.assertEqual(entities["top_n"], 10)
        self.assertEqual(entities["category"], "Fashion")

        sku_entities = EntityExtractor.extract_entities("Tại sao SKU-1002 bị rủi ro?")
        self.assertEqual(sku_entities["sku_id"], "SKU-1002")

    def test_multi_turn_context_resolution(self):
        """AC-04: Verifies multi-turn SKU inheritance (Turn 1 -> Turn 2)."""
        session_id = "multi_turn_session_01"

        # Turn 1: Explicit SKU
        res1 = self.classifier.classify("Tại sao SKU-001 bị Critical?", session_id=session_id)
        self.assertEqual(res1["entities"]["sku_id"], "SKU-001")
        self.assertEqual(res1["context"]["subject_id"], "SKU-001")

        # Turn 2: Implicit SKU ("Nó đang khóa bao nhiêu vốn?")
        res2 = self.classifier.classify("Nó đang khóa bao nhiêu vốn?", session_id=session_id)
        self.assertEqual(res2["primary_intent"], "CAPITAL_QUERY")
        self.assertEqual(res2["entities"]["sku_id"], "SKU-001")
        self.assertTrue(res2["context"]["inherited"])

    def test_multi_intent_compound_query(self):
        """AC-07: Verifies detection of compound multi-intents in single query."""
        res = self.classifier.classify("SKU-001 tại sao Critical và đang khóa bao nhiêu vốn?", session_id="s2")
        self.assertEqual(res["primary_intent"], "EXPLANATION_QUERY")
        self.assertIn("CAPITAL_QUERY", res["secondary_intents"])
        self.assertIn("RISK_EXPLANATION", res["context_requirements"])
        self.assertIn("CAPITAL_EXPOSURE", res["context_requirements"])

    def test_scope_guard_out_of_scope_blocking(self):
        """AC-09: Verifies Scope Guard blocks non-DSS out of scope queries."""
        res = self.classifier.classify("Dự đoán giá cổ phiếu hôm nay", session_id="s3")
        self.assertEqual(res["primary_intent"], "OUT_OF_SCOPE")
        self.assertTrue(res["is_out_of_scope"])
        self.assertEqual(res["next_action"], "FALLBACK")

    def test_ambiguity_handling(self):
        """AC-06: Verifies low confidence handling triggers AMBIGUOUS_INTENT and clarification prompt."""
        val = IntentValidator.validate_classification("UNKNOWN_INTENT", 0.30)
        self.assertEqual(val["validated_intent"], "AMBIGUOUS_INTENT")
        self.assertTrue(val["is_ambiguous"])
        self.assertIsNotNone(val["clarification_prompt"])
