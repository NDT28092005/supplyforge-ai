"""Credential and entitlement helpers for workspace integration providers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from supplyforge.models.integration import WorkspaceEntitlement


def _fernet() -> Fernet:
    configured_key = os.getenv('INTEGRATION_CREDENTIAL_ENCRYPTION_KEY', '').strip()
    if configured_key:
        return Fernet(configured_key.encode('utf-8'))
    # Development fallback is deterministic; deployed environments must supply
    # a separate rotation-capable key rather than reusing Django's secret.
    if getattr(settings, 'IS_DEPLOYED', False):
        raise RuntimeError('INTEGRATION_CREDENTIAL_ENCRYPTION_KEY is required in deployed environments.')
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest())
    return Fernet(derived)


def encrypt_credentials(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload, separators=(',', ':')).encode('utf-8')).decode('utf-8')


def decrypt_credentials(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode('utf-8')).decode('utf-8'))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise ValueError('Không thể đọc thông tin xác thực của kết nối.') from exc


def entitlement_active(workspace_id: int, feature_code: str = WorkspaceEntitlement.FEATURE_ERP_INTEGRATIONS) -> bool:
    entitlement = WorkspaceEntitlement.objects.filter(workspace_id=workspace_id, feature_code=feature_code).first()
    if not entitlement or not entitlement.is_enabled:
        return False
    return not entitlement.expires_at or entitlement.expires_at > timezone.now()


def webhook_secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()


def verify_webhook_signature(secret: str, timestamp: str, raw_body: bytes, signature: str, max_age_seconds: int = 300) -> bool:
    try:
        sent_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if timezone.is_naive(sent_at):
            sent_at = timezone.make_aware(sent_at)
        if abs((timezone.now() - sent_at).total_seconds()) > max_age_seconds:
            return False
    except (TypeError, ValueError):
        return False
    expected = hmac.new(secret.encode('utf-8'), timestamp.encode('utf-8') + b'.' + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or '')
