"""XGBoost Classifier Model Predictor Module."""
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple

class RiskPredictor:
    def __init__(self, model_pkl_path: Path):
        with open(model_pkl_path, "rb") as f:
            model_data = pickle.load(f)
        self.model        = model_data["model"]
        self.feature_cols = model_data["feature_cols"]
        self.le_y         = model_data["label_encoder"]
        self.classes      = list(self.model.classes_)
        
        self.critical_idx = self.classes.index(self.le_y.transform(["CRITICAL"])[0])
        self.high_idx     = self.classes.index(self.le_y.transform(["HIGH_RISK"])[0])

    def predict(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (predictions_encoded, predictions_labels, probabilities_matrix)."""
        X = df[self.feature_cols].values.astype(np.float32)
        probs = self.model.predict_proba(X)
        preds_enc = self.model.predict(X)
        preds_lbl = self.le_y.inverse_transform(preds_enc)
        return preds_enc, preds_lbl, probs
