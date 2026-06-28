from django.urls import path
from . import views

urlpatterns = [
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/candidates', views.get_candidates, name='get_candidates'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/merge', views.merge_products, name='merge_products'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/undo', views.undo_merge, name='undo_merge'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/ignore', views.ignore_pair, name='ignore_pair'),
]
