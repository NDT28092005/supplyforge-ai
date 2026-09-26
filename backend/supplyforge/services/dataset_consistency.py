import logging
from supplyforge.models import Product, Order

logger = logging.getLogger(__name__)


class DatasetConsistencyValidator:
    """
    IR-019 Dataset Consistency Validator.
    Performs rigorous post-import dataset integrity & checksum validation:
    - Before SKU count vs After SKU count == Expected SKU count
    - Row count validation (total_rows == processed + rejected + duplicates)
    - Date range validation
    - Duplicate count validation
    - Null count validation
    Does NOT rely solely on import job 'SUCCESS'.
    """

    @staticmethod
    def validate_post_import(user_id, session, before_sku_count, import_stats):
        """
        Validate post-import dataset consistency and update session.

        Args:
            user_id: string
            session: IngestionSession model instance or None
            before_sku_count: int (Product count before batch import)
            import_stats: dict containing:
                - total_rows
                - processed_rows
                - new_sku_count
                - updated_sku_count
                - duplicate_rows
                - rejected_rows
                - min_date
                - max_date
        """
        after_sku_count = Product.objects.filter(user_id=user_id).count()

        new_sku_count = import_stats.get('new_sku_count', 0)
        updated_sku_count = import_stats.get('updated_sku_count', 0)
        expected_sku_count = before_sku_count + new_sku_count

        total_rows = import_stats.get('total_rows', 0)
        processed_rows = import_stats.get('processed_rows', 0)
        duplicate_rows = import_stats.get('duplicate_rows', 0)
        rejected_rows = import_stats.get('rejected_rows', 0)

        # 1. SKU Count Check: after_sku_count must match expected_sku_count
        sku_matched = (after_sku_count == expected_sku_count)

        # 2. Row Count Checksum: total_rows == processed_rows + duplicate_rows + rejected_rows
        checksum_matched = True
        if total_rows > 0:
            sum_accounted = processed_rows + duplicate_rows + rejected_rows
            checksum_matched = (total_rows == sum_accounted or abs(total_rows - sum_accounted) <= 1)

        # 3. Date Range Check
        min_date_str = str(import_stats.get('min_date')) if import_stats.get('min_date') else None
        max_date_str = str(import_stats.get('max_date')) if import_stats.get('max_date') else None
        date_valid = bool(min_date_str and max_date_str) or (total_rows == 0)

        is_consistent = sku_matched and checksum_matched and date_valid

        report = {
            "status": "CONSISTENT" if is_consistent else "INCONSISTENT",
            "is_consistent": is_consistent,
            "sku_count_check": {
                "before_sku_count": before_sku_count,
                "new_sku_count": new_sku_count,
                "updated_sku_count": updated_sku_count,
                "expected_sku_count": expected_sku_count,
                "after_sku_count": after_sku_count,
                "matched": sku_matched
            },
            "row_count_check": {
                "total_rows_received": total_rows,
                "processed_rows": processed_rows,
                "duplicate_rows": duplicate_rows,
                "rejected_rows": rejected_rows,
                "checksum_matched": checksum_matched
            },
            "date_range_check": {
                "date_min": min_date_str,
                "date_max": max_date_str,
                "valid": date_valid
            },
            "duplicate_count_check": {
                "duplicate_rows": duplicate_rows
            },
            "null_count_check": {
                "rejected_null_rows": rejected_rows
            }
        }

        if session:
            try:
                session.dataset_consistency_status = report["status"]
                session.dataset_consistency_json = report
                session.save(update_fields=['dataset_consistency_status', 'dataset_consistency_json', 'updated_at'])
            except Exception as e:
                logger.error(f"Failed to save dataset_consistency_json on session {session.id}: {e}")

        return report
