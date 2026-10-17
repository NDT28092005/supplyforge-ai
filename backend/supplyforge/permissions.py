"""
AUTH-004: Role-Based Access Control (RBAC) Module
Defines system roles (OWNER, ADMIN, ANALYST, OPERATOR, VIEWER) and permission checks.
"""
from functools import wraps
from django.http import JsonResponse

# ── Roles ─────────────────────────────────────────────────────────────
ROLE_OWNER = 'OWNER'
ROLE_ADMIN = 'ADMIN'
ROLE_ANALYST = 'ANALYST'
ROLE_OPERATOR = 'OPERATOR'
ROLE_VIEWER = 'VIEWER'

ROLE_CHOICES = [
    (ROLE_OWNER, 'Owner'),
    (ROLE_ADMIN, 'Admin'),
    (ROLE_ANALYST, 'Analyst'),
    (ROLE_OPERATOR, 'Operator'),
    (ROLE_VIEWER, 'Viewer'),
]

# ── Permissions ───────────────────────────────────────────────────────
PERM_UPLOAD_DATA = 'upload_data'
PERM_DELETE_DATASET = 'delete_dataset'
PERM_RUN_SIMULATION = 'run_simulation'
PERM_EXECUTE_ACTION = 'execute_action'
PERM_VIEW_FINANCIAL = 'view_financial'

ROLE_PERMISSIONS = {
    ROLE_OWNER: {PERM_UPLOAD_DATA, PERM_DELETE_DATASET, PERM_RUN_SIMULATION, PERM_EXECUTE_ACTION, PERM_VIEW_FINANCIAL},
    ROLE_ADMIN: {PERM_UPLOAD_DATA, PERM_DELETE_DATASET, PERM_RUN_SIMULATION, PERM_EXECUTE_ACTION, PERM_VIEW_FINANCIAL},
    ROLE_ANALYST: {PERM_RUN_SIMULATION, PERM_VIEW_FINANCIAL},
    ROLE_OPERATOR: {PERM_UPLOAD_DATA, PERM_EXECUTE_ACTION},
    ROLE_VIEWER: set(),
}


def has_permission(role: str, permission: str) -> bool:
    """
    Checks if a role has the specified permission.
    """
    if not role:
        return False
    normalized_role = str(role).upper()
    allowed_perms = ROLE_PERMISSIONS.get(normalized_role, set())
    return permission in allowed_perms


def get_user_permissions(role: str) -> dict:
    """
    Returns a dictionary of all permissions and their boolean status for the given role.
    """
    if not role:
        role = ROLE_VIEWER
    normalized_role = str(role).upper()
    allowed_perms = ROLE_PERMISSIONS.get(normalized_role, set())
    return {
        PERM_UPLOAD_DATA: PERM_UPLOAD_DATA in allowed_perms,
        PERM_DELETE_DATASET: PERM_DELETE_DATASET in allowed_perms,
        PERM_RUN_SIMULATION: PERM_RUN_SIMULATION in allowed_perms,
        PERM_EXECUTE_ACTION: PERM_EXECUTE_ACTION in allowed_perms,
        PERM_VIEW_FINANCIAL: PERM_VIEW_FINANCIAL in allowed_perms,
    }


def require_role_permission(permission: str):
    """
    Decorator for Django view functions to enforce RBAC permissions.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Extract user role from request (attached by auth middleware or session)
            user_role = getattr(request, 'user_role', None)
            if not user_role and hasattr(request, 'user') and hasattr(request.user, 'role'):
                user_role = request.user.role

            if not user_role:
                return JsonResponse({
                    "error": "Yêu cầu chưa được xác thực.",
                    "code": "UNAUTHENTICATED",
                }, status=401)

            if not has_permission(user_role, permission):
                return JsonResponse({
                    "error": f"Tài khoản của bạn với vai trò '{user_role}' không có quyền thực hiện thao tác '{permission}'.",
                    "code": "PERMISSION_DENIED",
                    "required_permission": permission,
                    "user_role": user_role
                }, status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
