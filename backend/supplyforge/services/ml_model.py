"""
SupplyForge AI — Hybrid ML Model Pipeline (3-Tier Architecture)

Tier 1: Feature Validation
    Feature Store lookup → schema validation → dtype validation

Tier 2: Prediction Engine
    Primary: XGBClassifier + Isotonic Calibration
    Fallback: Baseline Logistic Sigmoid (original heuristic)

Architecture:
    Feature Store (offline snapshot)
        ↓ lookup SKU
    Feature Schema Gate
        ↓ validated feature vector
    Model Compatibility Gate (in ModelLoaderService)
        ↓
    XGBoost → Isotonic Calibrator → Risk Threshold
        ↓ or fallback
    Baseline Logistic Sigmoid
        ↓
    Prediction Result + engine_status metadata
"""

import math
import logging
from datetime import datetime, date, timedelta
from django.db import connection
from supplyforge.models import Product
from supplyforge.services.model_loader import (
    ModelLoaderService, FeatureStoreLoader,
    MLServiceError, FailureType,
)
from supplyforge.metrics import record_prediction

logger = logging.getLogger(__name__)


class HybridModelPipeline:
    """
    Hybrid Machine Learning Pipeline for SupplyForge AI 2.0.

    3-Tier Inference Architecture:
      Tier 1 — Feature Validation (Feature Store lookup + schema gate)
      Tier 2 — Primary Engine (XGBClassifier + Isotonic Calibration) or Fallback (Baseline Logistic)

    Prediction and Explanation fallback are INDEPENDENT.
    """

    # ================================================================
    # Tier 1: Feature Extraction (Django ORM — operational data)
    # ================================================================

    @staticmethod
    def extract_features(sku_id, workspace_id=1):
        """
        Phase 3 & 4: Feature Engineering.
        Extracts mathematical features from Django models for a given SKU.
        Returns a dictionary of raw features or None if SKU not found.
        """
        try:
            product = Product.objects.get(id=sku_id)
        except Product.DoesNotExist:
            return None

        # Determine user/shop scope
        user_id = product.user_id

        # 1. Sales Features (Phase 4: Sales)
        now = datetime.now()
        date_7d = now - timedelta(days=7)
        date_30d = now - timedelta(days=30)

        # Query sales quantities from OrderItem in last 7 and 30 days
        sql_sales = """
            SELECT 
                SUM(CASE WHEN o.created_at >= %s THEN oi.quantity ELSE 0 END) as sales_7d,
                SUM(CASE WHEN o.created_at >= %s THEN oi.quantity ELSE 0 END) as sales_30d
            FROM order_items oi
            JOIN orders o ON oi.order_id = o._id
            WHERE (oi.item_id = %s OR oi.sku = %s)
              AND o.user_id = %s
        """
        with connection.cursor() as cursor:
            cursor.execute(sql_sales, [date_7d, date_30d, product.item_id, product.item_sku, user_id])
            row = cursor.fetchone()
            sales_7d = float(row[0] or 0.0) if row else 0.0
            sales_30d = float(row[1] or 0.0) if row else 0.0

        # Sales velocity (units per day)
        sales_velocity = sales_30d / 30.0

        # Sales trend (velocity of last 7d vs preceding 23d)
        v_7 = sales_7d / 7.0
        v_prev = (sales_30d - sales_7d) / 23.0 if sales_30d > sales_7d else 0.0
        if v_prev > 0:
            sales_trend = v_7 / v_prev
        else:
            sales_trend = 1.0 if sales_7d > 0 else 0.0

        # 2. Inventory Features (Phase 4: Inventory)
        inventory_qty = float(product.stock or 0)
        cost_price = float(product.cost or 0.0)
        selling_price = float(product.price or 0.0)

        # Coverage days (Inventory days)
        if sales_velocity > 0:
            coverage_days = inventory_qty / sales_velocity
        else:
            coverage_days = 999.0

        # Inventory ratio: SKU inventory cost relative to shop's total inventory cost
        total_value_sql = "SELECT SUM(stock * cost) FROM products WHERE user_id = %s"
        with connection.cursor() as cursor:
            cursor.execute(total_value_sql, [user_id])
            res = cursor.fetchone()
            total_inv_cost = float(res[0] or 0.0) if res else 0.0

        sku_val = inventory_qty * cost_price
        inventory_ratio = sku_val / total_inv_cost if total_inv_cost > 0 else 0.0

        # 3. Expiration Feature (F&B / Shelf life)
        today = date.today()
        if product.expiration_date:
            expiration_days_left = max(0, (product.expiration_date - today).days)
        else:
            expiration_days_left = 999.0  # Non-perishable default

        # 4. Supplier Risk Feature (Phase 4: Supplier)
        # Use deterministic hash of SKU identifier to simulate delay rates (0% to 20%)
        sku_hash = abs(hash(str(product.id)))
        delay_rate = (sku_hash % 21) / 100.0

        return {
            "inventory_qty": inventory_qty,
            "cost_price": cost_price,
            "selling_price": selling_price,
            "sales_7d": sales_7d,
            "sales_30d": sales_30d,
            "sales_velocity": round(sales_velocity, 3),
            "inventory_coverage_days": round(coverage_days, 1),
            "inventory_ratio": round(inventory_ratio, 4),
            "expiration_days_left": float(expiration_days_left),
            "delay_rate": round(delay_rate, 2),
            "sales_trend": round(sales_trend, 2)
        }

    # ================================================================
    # Tier 2: Prediction Engine — Primary (XGBoost) or Fallback (Baseline)
    # ================================================================

    @staticmethod
    def predict_risk(sku_id, workspace_id=1):
        """
        3-Tier Risk Prediction.
        """
        import time
        t_pred_start = time.monotonic()
        inference_duration = None

        # ---- Tier 0: Extract operational features from Django ORM ----
        try:
            features = HybridModelPipeline.extract_features(sku_id, workspace_id)
            if not features:
                return None
            product = Product.objects.get(id=sku_id)
        except Exception as e:
            record_prediction(
                model="xgboost",
                model_version="v1",
                status="failed",
                duration=time.monotonic() - t_pred_start,
                error_type=getattr(e, 'failure_type', 'ML_ERROR')
            )
            raise

        # ---- Tier 1: Feature Store Lookup + Validation ----
        feature_store_result = None
        feature_vector = None
        feature_completeness = 0.0
        data_provenance = {"source": "django_orm", "snapshot_date": None, "is_offline_snapshot": False}

        try:
            feature_store_result = ModelLoaderService.lookup_sku_features(str(sku_id))
            if feature_store_result is not None:
                feature_vector = feature_store_result["feature_vector"]
                feature_completeness = feature_store_result["feature_completeness"]
                data_provenance = {
                    "source": "gold_feature_store",
                    "snapshot_date": feature_store_result["snapshot_date"],
                    "is_offline_snapshot": feature_store_result["is_offline_snapshot"],
                }
        except MLServiceError as e:
            if e.is_fallback_eligible:
                logger.warning(
                    "Feature Store lookup failed for SKU %s [%s]: %s",
                    sku_id, e.failure_type, e.message
                )
            else:
                record_prediction(
                    model="xgboost",
                    model_version="v1",
                    status="failed",
                    duration=time.monotonic() - t_pred_start,
                    error_type=getattr(e, 'failure_type', 'ML_ERROR')
                )
                raise  # SYSTEM_ERROR — propagate

        # ---- Tier 2: Prediction ----
        prediction_meta = {}
        risk_probability = None
        risk_level = None
        base_value = None

        # Attempt Primary Engine (XGBoost + Isotonic Calibration)
        if feature_vector is not None:
            try:
                model = ModelLoaderService.get_model()
                le = ModelLoaderService.get_label_encoder()
                manifest = ModelLoaderService.get_manifest()

                # Pure Model Inference timing
                t_inf_start = time.monotonic()
                probs = model.predict_proba(feature_vector)
                pred_enc = model.predict(feature_vector)
                inference_duration = time.monotonic() - t_inf_start

                classes = list(model.classes_)
                critical_idx = classes.index(le.transform(["CRITICAL"])[0])
                high_idx = classes.index(le.transform(["HIGH_RISK"])[0])

                # P(high risk) = P(CRITICAL) + P(HIGH_RISK)
                raw_risk_prob = float(probs[0][critical_idx] + probs[0][high_idx])

                # Isotonic Calibration
                calibrator = ModelLoaderService.get_calibrator()
                calibrated = False
                if calibrator is not None:
                    import numpy as np
                    risk_probability = float(
                        calibrator.predict(np.array([raw_risk_prob]))[0]
                    )
                    calibrated = True
                else:
                    risk_probability = raw_risk_prob

                risk_probability = max(0.0, min(1.0, risk_probability))

                # Risk level from classifier
                risk_level = str(le.inverse_transform(pred_enc)[0])

                # Base value for SHAP (average predicted probability across training data)
                rc_meta = manifest.get("risk_classifier", {})
                base_value = 0.88  # from training: 88.09% positive rate

                prediction_meta = {
                    "engine": "XGBOOST",
                    "model_version": f"risk-xgb-v{rc_meta.get('model_version', 'unknown')}",
                    "status": "PRIMARY",
                    "calibrated": calibrated,
                    "calibration_method": "isotonic" if calibrated else None,
                    "raw_probability": round(raw_risk_prob, 4),
                }

                logger.debug(
                    "Primary prediction for SKU %s: risk=%.4f (raw=%.4f), level=%s",
                    sku_id, risk_probability, raw_risk_prob, risk_level
                )

            except MLServiceError as e:
                if e.is_fallback_eligible:
                    logger.warning(
                        "Primary prediction failed for SKU %s [%s]: %s — falling back to baseline",
                        sku_id, e.failure_type, e.message
                    )
                    risk_probability = None
                else:
                    logger.error(
                        "Non-recoverable ML error for SKU %s [%s]: %s",
                        sku_id, e.failure_type, e.message
                    )
                    record_prediction(
                        model="xgboost",
                        model_version="v1",
                        status="failed",
                        duration=time.monotonic() - t_pred_start,
                        error_type=getattr(e, 'failure_type', 'ML_ERROR')
                    )
                    raise
            except Exception as e:
                logger.critical(
                    "Unexpected error in primary prediction for SKU %s: %s",
                    sku_id, e, exc_info=True
                )
                record_prediction(
                    model="xgboost",
                    model_version="v1",
                    status="failed",
                    duration=time.monotonic() - t_pred_start,
                    error_type="UNEXPECTED_ERROR"
                )
                raise

        # ---- Tier 2 Fallback: Baseline Logistic Sigmoid ----
        if risk_probability is None:
            risk_probability, risk_level = HybridModelPipeline._baseline_predict(features)
            base_value = 0.35  # baseline model's prior

            # Determine fallback reason
            if feature_vector is None:
                fallback_reason = FailureType.FEATURE_INVALID
            elif ModelLoaderService.get_load_error():
                fallback_reason = ModelLoaderService.get_load_error().failure_type
            else:
                fallback_reason = FailureType.PREDICTION_ERROR

            prediction_meta = {
                "engine": "BASELINE_LOGISTIC",
                "model_version": "baseline-v1.0",
                "status": "FALLBACK",
                "fallback_reason": fallback_reason,
                "calibrated": False,
            }

            logger.info(
                "Baseline prediction for SKU %s: risk=%.4f, level=%s, reason=%s",
                sku_id, risk_probability, risk_level, fallback_reason
            )

        total_duration = time.monotonic() - t_pred_start
        record_prediction(
            model=prediction_meta.get("engine", "xgboost").lower(),
            model_version=prediction_meta.get("model_version", "v1"),
            status=prediction_meta.get("status", "PRIMARY").lower(),
            duration=total_duration,
            inference_duration=inference_duration
        )

        return {
            "risk_probability": round(risk_probability, 4),
            "risk_level": risk_level,
            "decision_confidence": None,  # Computed by ShapExplanationService
            "base_value": base_value,
            "prediction": prediction_meta,
            "features": features,
            "feature_vector": feature_vector,
            "feature_completeness": feature_completeness,
            "data_provenance": data_provenance,
        }

    # ================================================================
    # Baseline Engine (Logistic Sigmoid — original heuristic)
    # ================================================================

    @staticmethod
    def _baseline_predict(features):
        """
        Original logistic sigmoid heuristic model.
        Used as fallback when XGBoost is unavailable.

        Returns (risk_probability, risk_level).
        """
        # Base Log-Odds for inventory risk is around -0.62 (probability = 0.35)
        base_log_odds = -0.62

        # Coefficients (heuristic)
        coef_coverage = -0.01
        coef_trend = 0.8
        coef_delay = 2.5
        coef_expiry = -0.05

        # Calculate contribution in log-odds space
        coverage_contrib = coef_coverage * (features["inventory_coverage_days"] - 30.0)
        coverage_contrib = max(-2.0, min(2.0, coverage_contrib))

        trend_contrib = coef_trend * (features["sales_trend"] - 1.0)
        delay_contrib = coef_delay * (features["delay_rate"] - 0.05)

        if features["expiration_days_left"] < 999.0:
            expiry_contrib = coef_expiry * (features["expiration_days_left"] - 30.0)
            expiry_contrib = max(0.0, expiry_contrib)
        else:
            expiry_contrib = 0.0

        # Sigmoid activation
        log_odds = base_log_odds + coverage_contrib + trend_contrib + delay_contrib + expiry_contrib
        probability = 1.0 / (1.0 + math.exp(-log_odds))
        probability = max(0.05, min(0.95, probability))

        # Determine risk level from probability
        if probability >= 0.80:
            risk_level = "CRITICAL"
        elif probability >= 0.60:
            risk_level = "HIGH_RISK"
        elif probability >= 0.40:
            risk_level = "MEDIUM_RISK"
        else:
            risk_level = "LOW_RISK"

        return probability, risk_level
