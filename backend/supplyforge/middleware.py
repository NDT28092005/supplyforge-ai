import threading
from django.db import models

_thread_locals = threading.local()

def get_current_tenant_id():
    return getattr(_thread_locals, 'tenant_id', None)

def set_current_tenant_id(tenant_id):
    _thread_locals.tenant_id = tenant_id

class TenantIsolationMiddleware:
    """
    Application-level Security Middleware for Shared Schema Multi-tenancy.
    Extracts tenant_id (or workspace_id / user_id) from HTTP headers or query params
    and stores it in thread-local storage for automatic ORM query scoping.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id = (
            request.headers.get('X-Tenant-ID') or 
            request.headers.get('X-Workspace-ID') or 
            request.GET.get('userId') or 
            request.GET.get('workspaceId') or 
            'user_default_001'
        )
        set_current_tenant_id(tenant_id)
        
        try:
            response = self.get_response(request)
        finally:
            set_current_tenant_id(None)
            
        return response


class TenantManager(models.Manager):
    """
    Custom Django Manager that automatically filters QuerySets by current tenant_id.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = get_current_tenant_id()
        if tenant_id:
            field_names = [f.name for f in self.model._meta.get_fields()]
            if 'user_id' in field_names:
                return qs.filter(user_id=tenant_id)
            elif 'workspace' in field_names or 'workspace_id' in field_names:
                return qs.filter(workspace_id=tenant_id)
        return qs
