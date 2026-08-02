"""
SupplyForge AI — App URL Configuration
========================================
All REST API endpoints consolidated cleanly into single supplyforge app.
"""

from django.urls import path
from supplyforge import views

urlpatterns = [
    # Health & System
    path('api/v1/ping', views.ping, name='ping'),
    path('api/v1/data/check', views.check_data, name='check_data'),

    # Authentication & User Management (Google OAuth + Local JWT + Odoo Sync)
    path('api/auth/google/callback', views.google_callback, name='google_callback'),
    path('api/auth/verify', views.verify_token, name='verify_token'),
    path('api/auth/register', views.register_user, name='register_user'),
    path('api/auth/login', views.login_user, name='login_user'),
    path('api/auth/google/complete-phone', views.google_complete_phone, name='google_complete_phone'),

    # Data Sync (JSON Batch)
    path('api/v1/sync/products', views.sync_products, name='sync_products'),
    path('api/v1/sync/orders', views.sync_orders, name='sync_orders'),

    # Dynamic CSV Import Engine (Streaming + Gemini AI Column Mapping)
    path('api/v1/import/analyze', views.analyze_file, name='analyze_file'),
    path('api/v1/import/process', views.process_file, name='process_file'),
    path('api/v1/import/clear', views.clear_data, name='clear_data'),

    # Leak Detector & Inventory Aging Dashboard
    path('api/v1/workspaces/<int:workspace_id>/dead-stock/refresh', views.refresh_dead_stock, name='refresh_dead_stock'),
    path('api/v1/workspaces/<int:workspace_id>/dead-stock', views.get_dead_stock, name='get_dead_stock'),
    path('api/v1/workspaces/<int:workspace_id>/aging', views.get_aging, name='get_aging'),

    # Recovery Copilot & Financial Liquidation Engine
    path('api/v1/workspaces/<int:workspace_id>/portfolio/command', views.get_portfolio_command, name='get_portfolio_command'),
    path('api/v1/workspaces/<int:workspace_id>/portfolio/financial-analysis', views.get_financial_analysis, name='get_financial_analysis'),
    path('api/v1/workspaces/<int:workspace_id>/sku/<str:sku_id>/xai', views.get_sku_xai, name='get_sku_xai'),

    # SKU Tinder (Levenshtein & Normalization Matching Engine)
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/candidates', views.get_candidates, name='get_candidates'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/merge', views.merge_products, name='merge_products'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/undo', views.undo_merge, name='undo_merge'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/ignore', views.ignore_pair, name='ignore_pair'),

    # Shopee Open API Integration (OAuth2 + HMAC Webhooks + Manual Sync)
    path('api/v1/shopee/oauth/authorize', views.shopee_oauth_authorize_url, name='shopee_oauth_authorize_url'),
    path('api/v1/shopee/oauth/callback', views.shopee_oauth_callback, name='shopee_oauth_callback'),
    path('api/v1/shopee/webhook', views.shopee_webhook, name='shopee_webhook'),
    path('api/v1/shopee/sync/trigger', views.trigger_sync, name='shopee_trigger_sync'),
    path('api/v1/shopee/sync/status', views.get_sync_status, name='shopee_sync_status'),
]
