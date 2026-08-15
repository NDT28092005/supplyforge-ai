"""SHAP TreeExplainer Module."""
import shap
import numpy as np
import pandas as pd
from typing import List, Dict

class SHAPExplainer:
    def __init__(self, model_obj, feature_cols: List[str], biz_name_map: Dict[str, str]):
        self.explainer = shap.TreeExplainer(model_obj)
        self.feature_cols = feature_cols
        self.biz_name_map = biz_name_map

    def explain_sku(self, X_row: np.ndarray, target_class_idx: int, top_k: int = 3) -> List[Dict]:
        """Compute top-k SHAP risk-increasing factors for a single SKU."""
        shap_vals = self.explainer.shap_values(X_row.reshape(1, -1))
        # Handle multi-class shape
        if len(shap_vals.shape) == 3:
            row_shap = shap_vals[0, :, target_class_idx]
        else:
            row_shap = shap_vals[0]

        top_indices = np.argsort(row_shap)[::-1][:top_k]
        evidence = []
        for idx in top_indices:
            f_name = self.feature_cols[idx]
            s_val  = float(row_shap[idx])
            o_val  = float(X_row[idx])
            b_name = self.biz_name_map.get(f_name, f_name)
            evidence.append({
                "feature": f_name,
                "business_name_vi": b_name,
                "shap_value": round(s_val, 4),
                "observed_value": str(round(o_val, 4)),
                "impact": "Tăng rủi ro bán chậm (+)" if s_val > 0 else "Giảm rủi ro bán chậm (-)"
            })
        return evidence
