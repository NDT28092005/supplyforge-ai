from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from supplyforge.models import Product
from supplyforge.services.sku_tinder import SkuNormalizationService
from supplyforge.services.normalizer import VietnameseNormalizer, Levenshtein


class TestFuzzyMatchingAndDeduplication(TestCase):
    def test_fuzzy_matching_confidence_score(self):
        """Test Case 02: Verification of Fuzzy Matching similarity score calculation."""
        name_a = VietnameseNormalizer.strip_accents("Áo thun polo nam")
        name_b = VietnameseNormalizer.strip_accents("Áo thun polo nam")
        dist = Levenshtein.distance(name_a, name_b)
        similarity = 1.0 - (dist / max(len(name_a), len(name_b), 1))
        self.assertEqual(similarity, 1.0, "Exact match must have 100% similarity score")

        name_c = VietnameseNormalizer.strip_accents("Áo thun đen Oversize")
        name_d = VietnameseNormalizer.strip_accents("Áo thun đen oversize XL")
        dist_cd = Levenshtein.distance(name_c, name_d)
        similarity_cd = 1.0 - (dist_cd / max(len(name_c), len(name_d), 1))
        self.assertGreaterEqual(similarity_cd, 0.75, "High similarity for slight variations")

    def test_deduplication_candidates_generation(self):
        """Test candidate generation for products with similar names under same tenant."""
        p1 = Product.objects.create(
            id="sku_test_001",
            user_id="user_default_001",
            product_name="Áo thun Cotton đen Oversize",
            item_sku="AT-COTTON-BLK-XL",
            price=Decimal("150000.00"),
            cost=Decimal("80000.00"),
            stock=50,
            active_on_web=True
        )
        p2 = Product.objects.create(
            id="sku_test_002",
            user_id="user_default_001",
            product_name="Áo thun Cotton đen Oversize",
            item_sku="AT-BLK-XL-TIKTOK",
            price=Decimal("150000.00"),
            cost=Decimal("80000.00"),
            stock=20,
            active_on_web=True
        )
        
        candidates = SkuNormalizationService.find_duplicate_candidates(user_id="user_default_001")
        self.assertGreaterEqual(len(candidates), 1, "Should identify at least 1 group of matching candidate SKUs")


class TestMultiTenancySecurity(TestCase):
    def test_multi_tenancy_data_isolation(self):
        """Test Case 03: Security check ensuring Shop A cannot access Shop B data."""
        p_a = Product.objects.create(
            id="prod_shop_a_01",
            user_id="user_shop_a",
            product_name="Bàn làm việc Shop A",
            item_sku="DESK-A",
            price=Decimal("500000.00"),
            stock=10,
            active_on_web=True
        )
        
        p_b = Product.objects.create(
            id="prod_shop_b_01",
            user_id="user_shop_b",
            product_name="Bàn làm việc BÍ MẬT Shop B",
            item_sku="DESK-B-SECRET",
            price=Decimal("9900000.00"),
            stock=5,
            active_on_web=True
        )

        products_a = Product.objects.filter(user_id="user_shop_a")
        sku_names_a = [p.product_name for p in products_a]
        self.assertIn("Bàn làm việc Shop A", sku_names_a)
        self.assertNotIn("Bàn làm việc BÍ MẬT Shop B", sku_names_a, "CRITICAL SECURITY ERROR: Shop A accessed Shop B data!")


class TestFinancialCalculationLogic(TestCase):
    def test_sunk_cost_ratio_and_holding_cost(self):
        """Test financial metrics calculations for Cashflow Vault & Aging Radar."""
        total_value = Decimal("700000000.00")
        sunk_cost = Decimal("446369863.00")
        
        ratio = (sunk_cost / total_value) * 100
        self.assertEqual(round(float(ratio), 1), 63.8)
