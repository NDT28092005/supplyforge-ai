"""Feature Engineering & Categorical Encoding Module at t0."""
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from typing import Tuple, Dict

def preprocess_features(df_gt: pd.DataFrame, df_fc: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, LabelEncoder]]:
    """Merge ground truth base data with forecast features and encode categoricals."""
    df = pd.merge(
        df_gt,
        df_fc.drop(columns=[c for c in df_fc.columns if c in df_gt.columns and c != "itemId"], errors="ignore"),
        on="itemId",
        how="left"
    ).fillna(0)

    encoders = {}
    for col, new_col in [("brand", "brand_enc"), ("categoryId", "category_enc"), ("demand_pattern", "pattern_enc")]:
        le = LabelEncoder()
        if col in df.columns:
            df[new_col] = le.fit_transform(df[col].astype(str).fillna("UNKNOWN"))
        else:
            df[new_col] = 0
        encoders[new_col] = le

    return df, encoders
