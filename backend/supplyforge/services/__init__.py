"""Lazy exports for application services.

Importing a focused service (for example S3 ingestion) must not initialize the
DSS/ML dependency graph. Workers load only the dependencies for their queue.
"""

from importlib import import_module


_EXPORTS = {
    'MerchantDSSWebService': ('.dss_service', 'MerchantDSSWebService'),
    'RegistrationRateLimiter': ('.rate_limiter', 'RegistrationRateLimiter'),
    'VietnameseNormalizer': ('.normalizer', 'VietnameseNormalizer'),
    'Levenshtein': ('.normalizer', 'Levenshtein'),
    'IndustryPlaybook': ('.industry', 'IndustryPlaybook'),
    'PLAYBOOKS': ('.industry', 'PLAYBOOKS'),
    'IndustryDetectionService': ('.industry', 'IndustryDetectionService'),
    'GeminiColumnMappingService': ('.ingestion', 'GeminiColumnMappingService'),
    'DynamicFileImportService': ('.ingestion', 'DynamicFileImportService'),
    'InventoryInsightService': ('.insight', 'InventoryInsightService'),
    'InventoryFinancialEngineService': ('.financial', 'InventoryFinancialEngineService'),
    'FinancialLiquidationEngine': ('.financial', 'FinancialLiquidationEngine'),
    'PortfolioOrchestrationService': ('.portfolio', 'PortfolioOrchestrationService'),
    'SkuNormalizationService': ('.sku_tinder', 'SkuNormalizationService'),
    'GeminiCopilotService': ('.gemini_copilot', 'GeminiCopilotService'),
    'OdooIntegrationService': ('.odoo', 'OdooIntegrationService'),
    'ShopeeClient': ('.shopee_client', 'ShopeeClient'),
    'ShopeeAPIError': ('.shopee_client', 'ShopeeAPIError'),
    'verify_webhook_signature': ('.shopee_client', 'verify_webhook_signature'),
    'ShopeeSyncService': ('.shopee_sync', 'ShopeeSyncService'),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    """Import a service only when a caller explicitly requests it."""
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}') from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
