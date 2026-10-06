"""
SF-OPS-06 Unit Tests — Telemetry Instrumentation for ingestion.py and ml_model.py
"""
import time
from unittest.mock import MagicMock, patch
from django.test import TestCase
from prometheus_client import REGISTRY

from supplyforge.metrics import (
    INGESTION_TOTAL,
    INGESTION_DURATION_SECONDS,
    INGESTION_ROWS_TOTAL,
    INGESTION_LAST_SUCCESS_TIMESTAMP,
    PREDICTION_TOTAL,
    PREDICTION_DURATION_SECONDS,
    MODEL_INFERENCE_DURATION_SECONDS,
)
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.services.ml_model import HybridModelPipeline


class IngestionTelemetryTest(TestCase):
    def test_ingestion_telemetry_success(self):
        """Verify process_batch_import records success metrics upon successful execution."""
        before_count = INGESTION_TOTAL.labels(
            pipeline="medallion", source_type="csv", status="success"
        )._value.get()
        before_rows = INGESTION_ROWS_TOTAL.labels(
            pipeline="medallion", source_type="csv"
        )._value.get()

        mock_result = {
            "status": "DATA_READY",
            "import_type": "INITIAL",
            "rows_received": 150,
        }

        with patch.object(
            DynamicFileImportService,
            "_process_batch_import_impl",
            return_value=mock_result,
        ):
            res = DynamicFileImportService.process_batch_import(
                file_obj=None, mapping_rule={}, user_id=1
            )

        self.assertEqual(res["status"], "DATA_READY")

        after_count = INGESTION_TOTAL.labels(
            pipeline="medallion", source_type="csv", status="success"
        )._value.get()
        after_rows = INGESTION_ROWS_TOTAL.labels(
            pipeline="medallion", source_type="csv"
        )._value.get()

        self.assertEqual(after_count, before_count + 1)
        self.assertEqual(after_rows, before_rows + 150)

        last_ts = INGESTION_LAST_SUCCESS_TIMESTAMP.labels(
            pipeline="medallion"
        )._value.get()
        self.assertGreater(last_ts, 0)

    def test_ingestion_telemetry_failure(self):
        """Verify process_batch_import records failure metrics when an exception is raised."""
        before_count = INGESTION_TOTAL.labels(
            pipeline="medallion", source_type="csv", status="failed"
        )._value.get()

        with patch.object(
            DynamicFileImportService,
            "_process_batch_import_impl",
            side_effect=ValueError("CSV Corrupted"),
        ):
            with self.assertRaises(ValueError):
                DynamicFileImportService.process_batch_import(
                    file_obj=None, mapping_rule={}, user_id=1
                )

        after_count = INGESTION_TOTAL.labels(
            pipeline="medallion", source_type="csv", status="failed"
        )._value.get()

        self.assertEqual(after_count, before_count + 1)


class MLPredictionTelemetryTest(TestCase):
    @patch("supplyforge.services.ml_model.ModelLoaderService.lookup_sku_features")
    @patch("supplyforge.services.ml_model.Product.objects.get")
    @patch("supplyforge.services.ml_model.HybridModelPipeline.extract_features")
    @patch("supplyforge.services.ml_model.ModelLoaderService.get_model")
    @patch("supplyforge.services.ml_model.ModelLoaderService.get_label_encoder")
    @patch("supplyforge.services.ml_model.ModelLoaderService.get_manifest")
    def test_ml_prediction_telemetry_success(
        self, mock_manifest, mock_encoder, mock_get_model, mock_extract, mock_product_get, mock_lookup_sku
    ):
        """Verify predict_risk records success & inference metrics for ML prediction."""
        import numpy as np
        mock_extract.return_value = {"sku_id": "SKU-001", "lead_time_days": 10}
        mock_product = MagicMock()
        mock_product_get.return_value = mock_product
        mock_lookup_sku.return_value = {
            "feature_vector": np.zeros((1, 25)),
            "feature_completeness": 1.0,
            "snapshot_date": "2026-10-01",
            "is_offline_snapshot": False
        }

        mock_model = MagicMock()
        mock_model.classes_ = [0, 1]
        mock_model.predict_proba.return_value = [[0.2, 0.8]]
        mock_model.predict.return_value = [1]
        mock_get_model.return_value = mock_model

        mock_le = MagicMock()
        mock_le.transform.side_effect = lambda val: [1] if "HIGH_RISK" in val or "CRITICAL" in val else [0]
        mock_le.inverse_transform.return_value = ["HIGH_RISK"]
        mock_encoder.return_value = mock_le

        mock_manifest.return_value = {"risk_classifier": {"model_version": "1.2.0"}}

        before_count = PREDICTION_TOTAL.labels(
            model="xgboost", model_version="risk-xgb-v1.2.0", status="primary"
        )._value.get()

        result = HybridModelPipeline.predict_risk(sku_id="SKU-001", workspace_id=1)

        self.assertIsNotNone(result)
        after_count = PREDICTION_TOTAL.labels(
            model="xgboost", model_version="risk-xgb-v1.2.0", status="primary"
        )._value.get()
        self.assertEqual(after_count, before_count + 1)

    @patch("supplyforge.services.ml_model.HybridModelPipeline.extract_features")
    def test_ml_prediction_telemetry_failure(self, mock_extract):
        """Verify predict_risk records failure metric with error_type label on SYSTEM_ERROR exception."""
        from supplyforge.services.model_loader import MLServiceError, FailureType

        mock_extract.side_effect = MLServiceError(
            failure_type=FailureType.SYSTEM_ERROR,
            message="Database query catastrophic failure"
        )

        before_fail_count = PREDICTION_TOTAL.labels(
            model="xgboost", model_version="v1", status="failed"
        )._value.get()

        with self.assertRaises(MLServiceError):
            HybridModelPipeline.predict_risk(sku_id="SKU-ERR", workspace_id=1)

        after_fail_count = PREDICTION_TOTAL.labels(
            model="xgboost", model_version="v1", status="failed"
        )._value.get()
        self.assertEqual(after_fail_count, before_fail_count + 1)
