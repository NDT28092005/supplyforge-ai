from django.urls import path, include
from . import views

urlpatterns = [
    # Health and Sync Core APIs
    path('api/v1/ping', views.ping, name='ping'),
    path('api/v1/products/check-data', views.check_data, name='check_data'),
    path('api/v1/products/sync', views.sync_products, name='sync_products'),
    path('api/v1/orders/sync', views.sync_orders, name='sync_orders'),

    # Include feature-specific URLs
    path('', include('core.features.ingestion.urls')),
    path('', include('core.features.sku_tinder.urls')),
    path('', include('core.features.leak_detector.urls')),
    path('', include('core.features.recovery_copilot.urls')),
]
