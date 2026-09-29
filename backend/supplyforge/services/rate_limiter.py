"""
SupplyForge AI — Registration Rate Limiter & Risk Evaluation Service (SEC-AUTH-001 & SEC-AUTH-004)
===================================================================================================
Provides sliding-window rate limiting and risk-based bot protection (CAPTCHA challenge)
for user registration.

SEC-AUTH-001: Rate limiting (IP, fingerprint, email, phone, risk signal).
SEC-AUTH-004: Adaptive Risk-Based CAPTCHA Challenge:
- Normal registration -> Processed without forcing CAPTCHA (frictionless UX).
- Suspicious / High-volume -> Triggers CAPTCHA / Challenge requirement.
"""

import os
import time
import threading
from django.core.cache import cache

class RegistrationRateLimiter:
    """
    SEC-AUTH-001 & SEC-AUTH-004: Thread-safe Rate Limiter and Risk Evaluator for registration endpoint.
    """
    _lock = threading.Lock()
    _memory_store = {}

    CAPTCHA_TRIGGER_ATTEMPTS = int(os.getenv('REGISTRATION_CAPTCHA_TRIGGER_ATTEMPTS', 3))

    @classmethod
    def get_policy(cls):
        max_attempts = int(os.getenv('REGISTRATION_RATE_LIMIT_MAX', 5))
        window_minutes = int(os.getenv('REGISTRATION_RATE_LIMIT_WINDOW_MINUTES', 15))
        return max_attempts, window_minutes

    @classmethod
    def get_attempt_count(cls, key_type: str, key_value: str, window_minutes: int = None) -> int:
        """
        Returns the number of active attempts for a specific identifier key.
        """
        if not key_value or not str(key_value).strip():
            return 0

        _, cfg_win = cls.get_policy()
        window_minutes = window_minutes if window_minutes is not None else cfg_win
        window_seconds = window_minutes * 60
        now = time.time()
        cache_key = f"sf_reg_limiter:{key_type}:{str(key_value).strip().lower()}"

        with cls._lock:
            timestamps = cache.get(cache_key)
            if timestamps is None:
                timestamps = cls._memory_store.get(cache_key, [])
            active_timestamps = [t for t in timestamps if now - t < window_seconds]
            return len(active_timestamps)

    @classmethod
    def evaluate_risk(cls, identifiers: dict, max_attempts_before_captcha: int = None) -> tuple[bool, str]:
        """
        SEC-AUTH-004: Evaluates whether a registration request is suspicious or high-volume.
        Returns: (requires_captcha, risk_reason)
        """
        threshold = max_attempts_before_captcha if max_attempts_before_captcha is not None else cls.CAPTCHA_TRIGGER_ATTEMPTS
        
        # 1. Check attempt frequency on IP & Device Fingerprint
        ip_attempts = cls.get_attempt_count('ip', identifiers.get('ip', ''))
        fp_attempts = cls.get_attempt_count('fingerprint', identifiers.get('fingerprint', ''))

        if ip_attempts >= threshold:
            return True, f"High volume registration attempts from IP ({ip_attempts} attempts)"
        if fp_attempts >= threshold:
            return True, f"High volume registration attempts from Device Fingerprint ({fp_attempts} attempts)"

        # 2. Check risk signal header / payload
        risk_sig = (identifiers.get('risk_signal') or '').lower()
        if any(term in risk_sig for term in ['bot', 'suspicious', 'proxy', 'tor', 'high_risk', 'challenge']):
            return True, f"Suspicious network risk signal detected ('{risk_sig}')"

        return False, "LOW_RISK"

    @classmethod
    def is_rate_limited(cls, identifiers: dict, max_attempts: int = None, window_minutes: int = None) -> tuple[bool, str, int]:
        """
        SEC-AUTH-001: Checks whether any identifier has breached max_attempts limit.
        """
        cfg_max, cfg_win = cls.get_policy()
        max_attempts = max_attempts if max_attempts is not None else cfg_max
        window_minutes = window_minutes if window_minutes is not None else cfg_win
        window_seconds = window_minutes * 60
        now = time.time()

        with cls._lock:
            for key_type, key_value in identifiers.items():
                if not key_value or not str(key_value).strip():
                    continue

                cache_key = f"sf_reg_limiter:{key_type}:{str(key_value).strip().lower()}"
                
                timestamps = cache.get(cache_key)
                if timestamps is None:
                    timestamps = cls._memory_store.get(cache_key, [])

                active_timestamps = [t for t in timestamps if now - t < window_seconds]

                if len(active_timestamps) >= max_attempts:
                    oldest_ts = active_timestamps[0]
                    retry_after = max(1, int(window_seconds - (now - oldest_ts)))
                    return True, f"{key_type}:{key_value}", retry_after

        return False, "", 0

    @classmethod
    def record_attempt(cls, identifiers: dict, window_minutes: int = None):
        """
        Appends timestamp for each non-empty identifier.
        """
        _, cfg_win = cls.get_policy()
        window_minutes = window_minutes if window_minutes is not None else cfg_win
        window_seconds = window_minutes * 60
        now = time.time()

        with cls._lock:
            for key_type, key_value in identifiers.items():
                if not key_value or not str(key_value).strip():
                    continue

                cache_key = f"sf_reg_limiter:{key_type}:{str(key_value).strip().lower()}"

                timestamps = cache.get(cache_key)
                if timestamps is None:
                    timestamps = cls._memory_store.get(cache_key, [])

                active_timestamps = [t for t in timestamps if now - t < window_seconds]
                active_timestamps.append(now)

                cls._memory_store[cache_key] = active_timestamps
                try:
                    cache.set(cache_key, active_timestamps, timeout=window_seconds)
                except Exception:
                    pass

    @classmethod
    def reset_all(cls):
        """Clear memory and cache stores (used for unit test resets)."""
        with cls._lock:
            cls._memory_store.clear()
            try:
                cache.clear()
            except Exception:
                pass
