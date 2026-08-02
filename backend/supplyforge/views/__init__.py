# supplyforge/views package
# Re-export all view functions for clean URL routing and external imports

from .health import ping, check_data
from .auth import (
    google_callback, verify_token, register_user, login_user, google_complete_phone,
)
from .sync import sync_products, sync_orders
from .ingestion import analyze_file, process_file, clear_data
from .leak_detector import refresh_dead_stock, get_dead_stock, get_aging
from .recovery_copilot import get_portfolio_command, get_financial_analysis
from .xai import get_sku_xai
from .sku_tinder import get_candidates, merge_products, undo_merge, ignore_pair
from .shopee import (
    shopee_oauth_authorize_url, shopee_oauth_callback,
    shopee_webhook, trigger_sync, get_sync_status,
)

__all__ = [
    'ping', 'check_data',
    'google_callback', 'verify_token', 'register_user', 'login_user', 'google_complete_phone',
    'sync_products', 'sync_orders',
    'analyze_file', 'process_file', 'clear_data',
    'refresh_dead_stock', 'get_dead_stock', 'get_aging',
    'get_portfolio_command', 'get_financial_analysis',
    'get_sku_xai',
    'get_candidates', 'merge_products', 'undo_merge', 'ignore_pair',
    'shopee_oauth_authorize_url', 'shopee_oauth_callback',
    'shopee_webhook', 'trigger_sync', 'get_sync_status',
]
