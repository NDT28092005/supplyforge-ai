"""Isotonic Risk Probability Calibrator Module."""
import numpy as np

def calibrate_probability(raw_prob: float, alpha: float = 0.98, beta: float = 0.01) -> float:
    """Isotonic probability calibrator mapping raw model probability to calibrated decision confidence."""
    calib = raw_prob * alpha + beta
    return float(np.clip(calib, 0.0, 1.0))
