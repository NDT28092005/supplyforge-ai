import os
import subprocess
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


def _get_git_commit_hash() -> str:
    """Retrieve current git short commit hash or environment fallback."""
    commit = os.getenv('GIT_COMMIT', '')
    if commit:
        return commit[:7]
    try:
        cmd_out = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=settings.BASE_DIR.parent,
            stderr=subprocess.DEVNULL
        )
        return cmd_out.decode('utf-8').strip()
    except Exception:
        return "37317c8"


@api_view(['GET'])
@permission_classes([AllowAny])
def get_version_info(request):
    """
    GET /api/version & /api/v1/version (Task 1.2 Version Endpoint)
    Returns application_version, commit, model_version, and feature_version.
    """
    app_version = getattr(settings, 'APP_VERSION', '1.0.0')
    commit_hash = _get_git_commit_hash()
    model_version = os.getenv('MODEL_VERSION', 'risk-v1.0.0')
    feature_version = os.getenv('FEATURE_VERSION', 'FV-2.0')

    return Response({
        "application_version": app_version,
        "commit": commit_hash,
        "model_version": model_version,
        "feature_version": feature_version,
        "api_versions": {
            "current": "v2",
            "supported": ["v1", "v2"],
            "legacy_unversioned": "v1",
            "deprecation_policy": (
                "v1 remains supported until a versioned sunset date is announced; "
                "clients should migrate new integrations to v2."
            ),
        },
    }, status=200)
