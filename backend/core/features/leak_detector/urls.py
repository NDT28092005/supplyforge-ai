from django.urls import path
from . import views

urlpatterns = [
    path('api/v1/workspaces/<int:workspace_id>/dashboard/dead-stock/refresh', views.refresh_dead_stock, name='refresh_dead_stock'),
    path('api/v1/workspaces/<int:workspace_id>/dashboard/dead-stock', views.get_dead_stock, name='get_dead_stock'),
    path('api/v1/workspaces/<int:workspace_id>/dashboard/aging', views.get_aging, name='get_aging'),
]
