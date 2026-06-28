import unicodedata
import re
from decimal import Decimal
from django.db import transaction
from core.models import Product, SkuMergeHistory, IgnoredSkuPair

class VietnameseNormalizer:
    @staticmethod
    def strip_accents(input_str):
        if not input_str:
            return ""
        replaced = re.sub(r'đ', 'd', input_str)
        replaced = re.sub(r'Đ', 'D', replaced)
        decomposed = unicodedata.normalize('NFD', replaced)
        stripped = "".join([c for c in decomposed if not unicodedata.combining(c)])
        return stripped.lower()


class Levenshtein:
    @staticmethod
    def distance(a, b):
        if a is None:
            a = ""
        if b is None:
            b = ""
        n, m = len(a), len(b)
        if n == 0:
            return m
        if m == 0:
            return n

        prev = list(range(m + 1))
        curr = [0] * (m + 1)

        for i in range(1, n + 1):
            curr[0] = i
            ca = a[i - 1]
            for j in range(1, m + 1):
                cost = 0 if ca == b[j - 1] else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            prev = list(curr)

        return prev[m]


class SkuNormalizationService:
    @staticmethod
    def find_duplicate_candidates(user_id):
        # Fetch ignored pairs to filter out (Human-in-the-loop)
        ignored = set()
        for pair in IgnoredSkuPair.objects.filter(user_id=user_id):
            ignored.add((pair.sku_a_id, pair.sku_b_id))
            ignored.add((pair.sku_b_id, pair.sku_a_id))

        products = list(Product.objects.filter(user_id=user_id, active_on_web=True))
        groups = []
        visited = [False] * len(products)

        for i in range(len(products)):
            if visited[i]:
                continue
            group = [products[i]]
            visited[i] = True

            for j in range(i + 1, len(products)):
                if visited[j]:
                    continue
                
                # Check if ignored previously
                if (products[i].id, products[j].id) in ignored:
                    continue

                if SkuNormalizationService.is_similar(products[i], products[j]):
                    group.append(products[j])
                    visited[j] = True

            if len(group) > 1:
                groups.append(group)

        return groups

    @staticmethod
    def is_similar(a, b):
        if a.item_sku and b.item_sku and a.item_sku.strip().lower() == b.item_sku.strip().lower():
            return True
        
        if a.product_name and b.product_name:
            name_a = VietnameseNormalizer.strip_accents(a.product_name.strip().lower())
            name_b = VietnameseNormalizer.strip_accents(b.product_name.strip().lower())
            
            dist = Levenshtein.distance(name_a, name_b)
            max_len = max(len(name_a), len(name_b), 1)
            similarity = 1.0 - (dist / max_len)

            return similarity >= 0.65 or (name_b in name_a) or (name_a in name_b)

        return False

    @staticmethod
    @transaction.atomic
    def merge_products(parent_id, child_id):
        try:
            parent = Product.objects.get(id=parent_id)
            child = Product.objects.get(id=child_id)
        except Product.DoesNotExist:
            raise ValueError("Product not found")

        # Save history for Undo/Revert support
        SkuMergeHistory.objects.create(
            parent_product=parent,
            child_product=child,
            original_child_stock=child.stock or 0,
            original_child_cost=child.cost or Decimal('0.00')
        )

        parent_stock = parent.stock or 0
        parent_cost = Decimal(str(parent.cost or 0.0))
        child_stock = child.stock or 0
        child_cost = Decimal(str(child.cost or 0.0))

        total_stock = parent_stock + child_stock
        total_value = (parent_cost * parent_stock) + (child_cost * child_stock)

        child.active_on_web = False
        child.save()

        parent.stock = total_stock
        if total_stock > 0:
            parent.cost = total_value / Decimal(total_stock)
        else:
            if not parent.cost:
                parent.cost = child_cost
        parent.save()

    @staticmethod
    @transaction.atomic
    def undo_merge(parent_id, child_id):
        try:
            history = SkuMergeHistory.objects.filter(parent_product_id=parent_id, child_product_id=child_id).latest('merged_at')
        except SkuMergeHistory.DoesNotExist:
            raise ValueError("Không tìm thấy nhật ký gộp cho cặp sản phẩm này.")

        parent = Product.objects.get(id=parent_id)
        child = Product.objects.get(id=child_id)

        # Restore child properties
        child.active_on_web = True
        child.stock = history.original_child_stock
        child.cost = history.original_child_cost
        child.save()

        # Recalculate parent properties
        parent_stock_before = parent.stock or 0
        parent_stock_after = max(0, parent_stock_before - history.original_child_stock)

        parent_cost_before = Decimal(str(parent.cost or 0.0))
        parent_value_before = parent_cost_before * parent_stock_before
        child_value = Decimal(str(history.original_child_cost)) * history.original_child_stock

        parent_value_after = max(Decimal('0.00'), parent_value_before - child_value)

        parent.stock = parent_stock_after
        if parent_stock_after > 0:
            parent.cost = parent_value_after / Decimal(parent_stock_after)
        else:
            parent.cost = Decimal('0.00')
        parent.save()

        # Clear history record
        history.delete()

    @staticmethod
    def ignore_pair(sku_a_id, sku_b_id, user_id):
        IgnoredSkuPair.objects.get_or_create(
            sku_a_id=sku_a_id,
            sku_b_id=sku_b_id,
            user_id=user_id
        )
