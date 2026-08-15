"""Input Data Ingestion & Validation Module."""
import pandas as pd
from typing import Tuple, List

REQUIRED_INPUT_COLS = ["itemId"]
FORBIDDEN_FUTURE_TARGETS = ["future_qty_60d", "drr_60d", "future_qty_30d"]

def validate_input_data(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Validate schema compliance and check for nulls or forbidden leakage columns."""
    errors = []
    
    # Check required columns
    missing_req = [c for c in REQUIRED_INPUT_COLS if c not in df.columns]
    if missing_req:
        errors.append(f"Missing required columns: {missing_req}")
        
    # Check forbidden leakage columns
    leaked = [c for c in FORBIDDEN_FUTURE_TARGETS if c in df.columns]
    if leaked:
        errors.append(f"Forbidden temporal leakage columns detected: {leaked}")
        
    passed = len(errors) == 0
    return passed, errors
