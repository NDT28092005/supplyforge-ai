"""
SupplyForge AI — Model Loader Service (Singleton + Compatibility Gate)

Manages thread-safe, one-time loading and caching of:
  1. Risk Classifier (XGBClassifier) from model_manifest.json
  2. Isotonic Calibrator from risk_calibrator.pkl
  3. TreeSHAP Explainer (shap.TreeExplainer)
  4. Gold Feature Store (parquet lookup by SKU)

Provides Model Compatibility Gate validation before allowing inference.

Architecture:
  Model File → Loadable? → Correct type? → Feature count/names/order? →
  Label classes? → Smoke test? → ✅ COMPATIBLE

Failure Classification:
  MODEL_UNAVAILABLE   — .pkl missing           → Fallback eligible
  MODEL_INCOMPATIBLE  — Schema mismatch         → Fallback eligible
  FEATURE_INVALID     — Feature vector invalid   → Fallback eligible
  PREDICTION_ERROR    — model.predict() failed   → Fallback eligible
  EXPLANATION_ERROR   — TreeSHAP failed          → Fallback eligible (SHAP only)
  SYSTEM_ERROR        — DB/infra/programming bug → NOT fallback eligible
"""

import json
import logging
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================
# Failure Classification
# ============================================================

class FailureType:
    """Typed failure categories for ML service errors."""
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_INCOMPATIBLE = "MODEL_INCOMPATIBLE"
    FEATURE_INVALID = "FEATURE_INVALID"
    PREDICTION_ERROR = "PREDICTION_ERROR"
    EXPLANATION_ERROR = "EXPLANATION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


FALLBACK_ELIGIBLE = {
    FailureType.MODEL_UNAVAILABLE,
    FailureType.MODEL_INCOMPATIBLE,
    FailureType.FEATURE_INVALID,
    FailureType.PREDICTION_ERROR,
    FailureType.EXPLANATION_ERROR,
}


class MLServiceError(Exception):
    """Base exception for ML service errors with typed classification."""
    def __init__(self, failure_type: str, message: str):
        self.failure_type = failure_type
        self.message = message
        super().__init__(f"[{failure_type}] {message}")

    @property
    def is_fallback_eligible(self):
        return self.failure_type in FALLBACK_ELIGIBLE


# ============================================================
# Model Compatibility Gate
# ============================================================

class ModelCompatibilityGate:
    """
    Validates model artifact against expected schema before allowing predictions.

    Checks (in order):
      1. Dict structure with 'model' key
      2. Model type == XGBClassifier
      3. Feature count == 25
      4. Feature names match canonical list (ORDER-SENSITIVE)
      5. Label classes match {CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK}
      6. Smoke test: predict_proba on zero vector returns valid shape and sum ≈ 1.0
    """

    EXPECTED_MODEL_TYPE = "XGBClassifier"
    EXPECTED_FEATURE_COUNT = 25
    EXPECTED_FEATURE_NAMES = [
        "adi", "cv2", "zero_rate_90d", "zero_rate_full",
        "sales_velocity_90d", "sales_velocity_full", "sales_last_30d",
        "past_total_sold", "dsls", "active_30d", "active_90d",
        "n_observation_days", "forecast_7d", "forecast_14d",
        "forecast_30d", "forecast_trend", "demand_probability",
        "expected_demand_daily", "price", "cost", "cost_imputed",
        "promo_rate", "brand_enc", "category_enc", "pattern_enc"
    ]
    EXPECTED_LABEL_CLASSES = {"CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"}

    @classmethod
    def validate(cls, model_data: dict) -> tuple:
        """
        Validate model artifact for compatibility.

        Returns:
            (is_valid: bool, error_message: str)
        """
        # 1. Check dict structure
        if not isinstance(model_data, dict):
            return False, f"MODEL_INCOMPATIBLE: expected dict, got {type(model_data).__name__}"

        # 2. Check model key exists
        model = model_data.get("model")
        if model is None:
            return False, "MODEL_INCOMPATIBLE: 'model' key missing from artifact dict"

        # 3. Check model type
        actual_type = type(model).__name__
        if actual_type != cls.EXPECTED_MODEL_TYPE:
            return False, f"MODEL_INCOMPATIBLE: expected model type '{cls.EXPECTED_MODEL_TYPE}', got '{actual_type}'"

        # 4. Check feature count
        feature_cols = model_data.get("feature_cols", [])
        if len(feature_cols) != cls.EXPECTED_FEATURE_COUNT:
            return False, (
                f"MODEL_INCOMPATIBLE: expected {cls.EXPECTED_FEATURE_COUNT} features, "
                f"got {len(feature_cols)}"
            )

        # 5. Check feature names AND order (order-sensitive)
        if feature_cols != cls.EXPECTED_FEATURE_NAMES:
            mismatches = []
            for i, (expected, actual) in enumerate(zip(cls.EXPECTED_FEATURE_NAMES, feature_cols)):
                if expected != actual:
                    mismatches.append(f"[{i}] expected '{expected}', got '{actual}'")
            if mismatches:
                return False, (
                    f"MODEL_INCOMPATIBLE: feature name/order mismatch at: "
                    f"{'; '.join(mismatches[:5])}"
                )
            # Length check already done, so if we're here it's a length issue
            return False, "MODEL_INCOMPATIBLE: feature list length mismatch after name comparison"

        # 6. Check label classes
        le = model_data.get("label_encoder")
        if le is not None:
            actual_classes = set(str(c) for c in le.classes_)
            if actual_classes != cls.EXPECTED_LABEL_CLASSES:
                return False, (
                    f"MODEL_INCOMPATIBLE: expected label classes {cls.EXPECTED_LABEL_CLASSES}, "
                    f"got {actual_classes}"
                )

        # 7. Smoke test — predict a zero vector
        try:
            X_smoke = np.zeros((1, cls.EXPECTED_FEATURE_COUNT), dtype=np.float32)
            probs = model.predict_proba(X_smoke)
            expected_shape = (1, len(cls.EXPECTED_LABEL_CLASSES))
            if probs.shape != expected_shape:
                return False, (
                    f"MODEL_INCOMPATIBLE: smoke test output shape {probs.shape}, "
                    f"expected {expected_shape}"
                )
            if not np.allclose(probs.sum(axis=1), 1.0, atol=0.05):
                return False, (
                    f"MODEL_INCOMPATIBLE: smoke test probabilities sum={probs.sum(axis=1)[0]:.4f}, "
                    f"expected ≈ 1.0"
                )
        except Exception as e:
            return False, f"MODEL_INCOMPATIBLE: smoke test prediction failed: {e}"

        return True, "OK"


# ============================================================
# Feature Store Loader
# ============================================================

class FeatureStoreLoader:
    """
    Loads and validates the Gold Feature Store (offline snapshot).

    Governance checks:
      - feature_version matches model manifest
      - feature names/count match feature_schema.json
      - SKU lookup with missing-feature validation
      - Freshness metadata exposed (is_offline_snapshot, snapshot_date)
    """

    _lock = threading.Lock()
    _df = None
    _metadata = None
    _is_loaded = False
    _load_error = None

    @classmethod
    def _load_once(cls, project_root: Path, manifest: dict):
        """Thread-safe lazy load of Feature Store parquet."""
        if cls._is_loaded:
            return
        with cls._lock:
            if cls._is_loaded:
                return
            try:
                cls._do_load(project_root, manifest)
                cls._is_loaded = True
            except MLServiceError as e:
                cls._load_error = e
                cls._is_loaded = True
                logger.warning("Feature Store loading failed [%s]: %s", e.failure_type, e.message)

    @classmethod
    def _do_load(cls, project_root: Path, manifest: dict):
        import pandas as pd

        fs_meta = manifest.get("feature_store")
        if not fs_meta:
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                "feature_store not defined in model_manifest.json"
            )

        parquet_path = project_root / fs_meta["location"]
        if not parquet_path.exists():
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                f"Feature Store parquet not found: {parquet_path}"
            )

        cls._df = pd.read_parquet(parquet_path)

        # Load metadata
        meta_path = project_root / fs_meta.get("metadata", "")
        if meta_path.exists():
            with open(meta_path, "r") as f:
                cls._metadata = json.load(f)
        else:
            cls._metadata = {}

        # Validate feature version matches manifest
        expected_fv = manifest.get("risk_classifier", {}).get("feature_version")
        actual_fv = fs_meta.get("feature_version")
        if expected_fv and actual_fv and expected_fv != actual_fv:
            raise MLServiceError(
                FailureType.MODEL_INCOMPATIBLE,
                f"Feature Store version '{actual_fv}' != model expected '{expected_fv}'"
            )

        # Validate feature names present
        expected_features = ModelCompatibilityGate.EXPECTED_FEATURE_NAMES
        missing = [f for f in expected_features if f not in cls._df.columns]
        if missing:
            raise MLServiceError(
                FailureType.MODEL_INCOMPATIBLE,
                f"Feature Store missing columns: {missing}"
            )

        logger.info(
            "Feature Store loaded: %d SKUs, version=%s, snapshot=%s (offline=%s)",
            len(cls._df),
            actual_fv,
            fs_meta.get("snapshot_date", "unknown"),
            fs_meta.get("is_offline_snapshot", True)
        )

    @classmethod
    def lookup_sku(cls, sku_id: str) -> dict:
        """
        Lookup a SKU's canonical feature vector from the Feature Store.

        Returns:
            dict with keys:
              - 'feature_vector': np.ndarray of shape (1, 25) in canonical order
              - 'feature_completeness': float 0.0-1.0
              - 'raw_features': dict of feature_name -> value
              - 'snapshot_date': str
              - 'is_offline_snapshot': bool
            Or None if SKU not found.

        Raises:
            MLServiceError(FEATURE_INVALID) if SKU found but features are invalid.
        """
        if cls._load_error:
            raise cls._load_error
        if cls._df is None:
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                "Feature Store not loaded"
            )

        feature_cols = ModelCompatibilityGate.EXPECTED_FEATURE_NAMES
        mask = cls._df["itemId"].astype(str) == str(sku_id)
        if mask.sum() == 0:
            return None

        row = cls._df[mask].iloc[0]
        raw_features = {col: float(row[col]) for col in feature_cols}

        # Compute feature completeness (non-NaN, non-zero meaningful check)
        import pandas as pd
        total = len(feature_cols)
        valid_count = sum(1 for v in raw_features.values() if pd.notna(v))
        feature_completeness = valid_count / total if total > 0 else 0.0

        # Build ordered feature vector
        feature_vector = np.array(
            [[raw_features[col] for col in feature_cols]],
            dtype=np.float32
        )

        # Validate no NaN in feature vector
        if np.any(np.isnan(feature_vector)):
            nan_features = [col for col, v in raw_features.items() if np.isnan(v)]
            raise MLServiceError(
                FailureType.FEATURE_INVALID,
                f"NaN values in features: {nan_features}"
            )

        manifest = ModelLoaderService.get_manifest()
        fs_meta = manifest.get("feature_store", {})

        return {
            "feature_vector": feature_vector,
            "feature_completeness": feature_completeness,
            "raw_features": raw_features,
            "snapshot_date": fs_meta.get("snapshot_date", "unknown"),
            "is_offline_snapshot": fs_meta.get("is_offline_snapshot", True),
        }


# ============================================================
# Model Loader Service (Singleton)
# ============================================================

class ModelLoaderService:
    """
    Thread-safe Singleton service for loading and caching ML model artifacts.

    Initialization sequence (one-time, on first access):
      1. Read models/model_manifest.json
      2. Load risk_classifier .pkl artifact
      3. Run ModelCompatibilityGate.validate()
      4. Load Isotonic Calibrator
      5. Initialize shap.TreeExplainer (if available)
      6. Load Gold Feature Store

    Public API:
      - get_model()         → XGBClassifier instance
      - get_explainer()     → shap.TreeExplainer or None
      - get_calibrator()    → IsotonicRegression or None
      - get_feature_cols()  → list of 25 feature names
      - get_label_encoder() → LabelEncoder
      - get_manifest()      → dict
      - is_available()      → bool
      - get_load_error()    → MLServiceError or None
    """

    _lock = threading.Lock()
    _model_data = None
    _xgb_model = None
    _lgb_model = None
    _shap_explainer = None
    _calibrator = None
    _feature_cols = None
    _label_encoder = None
    _manifest = None
    _is_loaded = False
    _load_error = None

    @classmethod
    def _load_once(cls):
        """Thread-safe lazy initialization. Called once on first access."""
        if cls._is_loaded:
            return
        with cls._lock:
            if cls._is_loaded:
                return
            try:
                cls._do_load()
                cls._is_loaded = True
            except MLServiceError as e:
                cls._load_error = e
                cls._is_loaded = True  # Mark as "attempted" to avoid retry loops
                logger.warning(
                    "ModelLoaderService initialization failed [%s]: %s",
                    e.failure_type, e.message
                )

    @classmethod
    def _do_load(cls):
        """Full initialization sequence."""
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        manifest_path = project_root / "models" / "model_manifest.json"

        # 1. Read manifest
        if not manifest_path.exists():
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                f"Model manifest not found: {manifest_path}"
            )
        with open(manifest_path, "r", encoding="utf-8") as f:
            cls._manifest = json.load(f)

        # 2. Locate and load risk classifier artifact
        rc_meta = cls._manifest.get("risk_classifier")
        if not rc_meta:
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                "'risk_classifier' not defined in model_manifest.json"
            )

        pkl_path = project_root / "models" / rc_meta["artifact"]
        if not pkl_path.exists():
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                f"Model artifact not found: {pkl_path}"
            )

        import joblib
        try:
            cls._model_data = joblib.load(pkl_path)
        except Exception as e:
            raise MLServiceError(
                FailureType.MODEL_UNAVAILABLE,
                f"Failed to unpickle model artifact: {e}"
            )

        # 3. Model Compatibility Gate
        is_valid, error_msg = ModelCompatibilityGate.validate(cls._model_data)
        if not is_valid:
            raise MLServiceError(FailureType.MODEL_INCOMPATIBLE, error_msg)

        # 4. Extract components
        cls._xgb_model = cls._model_data["model"]
        cls._feature_cols = cls._model_data["feature_cols"]
        cls._label_encoder = cls._model_data["label_encoder"]

        # 5. Load Isotonic Calibrator
        cal_artifact_name = rc_meta.get("calibration_artifact", "risk_calibrator.pkl")
        cal_path = project_root / "models" / cal_artifact_name
        if cal_path.exists():
            try:
                cal_data = joblib.load(cal_path)
                cls._calibrator = cal_data.get("calibrator") if isinstance(cal_data, dict) else cal_data
                logger.info(
                    "Isotonic Calibrator loaded (method=%s, ECE=%s)",
                    cal_data.get("method", "unknown"),
                    cal_data.get("ece", "N/A")
                )
            except Exception as e:
                logger.warning("Calibrator load failed: %s — using uncalibrated probs", e)
                cls._calibrator = None
        else:
            logger.warning("Calibrator artifact not found: %s", cal_path)
            cls._calibrator = None

        # 6. Initialize TreeExplainer (one-time cost)
        try:
            import shap
            cls._shap_explainer = shap.TreeExplainer(cls._xgb_model)
            logger.info(
                "TreeExplainer initialized successfully for %s v%s",
                rc_meta["model_name"], rc_meta["model_version"]
            )
        except Exception as e:
            logger.warning(
                "TreeExplainer initialization failed: %s — SHAP will use Linear Proxy fallback",
                e
            )
            cls._shap_explainer = None  # SHAP fallback only; model prediction still valid

        # 7. Load LightGBM Demand Forecaster
        df_meta = cls._manifest.get("demand_forecaster")
        if df_meta:
            lgb_path = project_root / "models" / df_meta.get("artifact", "best_lightgbm.pkl")
            if lgb_path.exists():
                try:
                    cls._lgb_model = joblib.load(lgb_path)
                    logger.info("LightGBM Demand Forecaster loaded: %s v%s", df_meta["model_name"], df_meta["model_version"])
                except Exception as e:
                    logger.warning("LightGBM load failed: %s", e)
                    cls._lgb_model = None

        # 8. Load Feature Store
        FeatureStoreLoader._load_once(project_root, cls._manifest)
        if FeatureStoreLoader._load_error:
            logger.warning(
                "Feature Store unavailable: %s — SKU lookup will fail, fallback to baseline",
                FeatureStoreLoader._load_error.message
            )

        logger.info(
            "ModelLoaderService ready: %s v%s (%d features, %d classes, calibrator=%s, SHAP=%s, LightGBM=%s)",
            rc_meta["model_name"],
            rc_meta["model_version"],
            len(cls._feature_cols),
            len(cls._label_encoder.classes_),
            "isotonic" if cls._calibrator else "none",
            "TreeExplainer" if cls._shap_explainer else "proxy",
            "loaded" if cls._lgb_model else "none"
        )

    # ---- Public API ----

    @classmethod
    def get_model(cls):
        """Returns XGBClassifier instance. Raises MLServiceError if unavailable."""
        cls._load_once()
        if cls._load_error:
            raise cls._load_error
        return cls._xgb_model

    @classmethod
    def get_lightgbm_model(cls):
        """Returns LightGBM Booster instance for demand forecasting or None."""
        cls._load_once()
        return cls._lgb_model

    @classmethod
    def get_explainer(cls):
        """Returns shap.TreeExplainer or None (does not raise — SHAP is optional)."""
        cls._load_once()
        return cls._shap_explainer

    @classmethod
    def get_calibrator(cls):
        """Returns IsotonicRegression calibrator or None."""
        cls._load_once()
        return cls._calibrator

    @classmethod
    def get_feature_cols(cls):
        """Returns list of 25 feature names in canonical order."""
        cls._load_once()
        if cls._load_error:
            raise cls._load_error
        return cls._feature_cols

    @classmethod
    def get_label_encoder(cls):
        """Returns LabelEncoder for risk classes."""
        cls._load_once()
        if cls._load_error:
            raise cls._load_error
        return cls._label_encoder

    @classmethod
    def get_manifest(cls):
        """Returns model_manifest.json dict (available even if model load failed)."""
        cls._load_once()
        return cls._manifest or {}

    @classmethod
    def is_available(cls):
        """Returns True if primary ML model is loaded and ready."""
        cls._load_once()
        return cls._xgb_model is not None and cls._load_error is None

    @classmethod
    def get_load_error(cls):
        """Returns MLServiceError if loading failed, None otherwise."""
        cls._load_once()
        return cls._load_error

    @classmethod
    def lookup_sku_features(cls, sku_id: str):
        """
        Convenience: lookup SKU from Feature Store.

        Returns dict with feature_vector, feature_completeness, raw_features,
        snapshot_date, is_offline_snapshot. Or None if SKU not found.
        """
        cls._load_once()
        return FeatureStoreLoader.lookup_sku(sku_id)
