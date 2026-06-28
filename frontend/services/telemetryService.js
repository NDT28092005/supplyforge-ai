angular.module('supplyForgeApp')
    .factory('telemetryService', ['$window', '$log', function ($window, $log) {
        // Initialize PostHog and Sentry wrappers safely
        var posthog = $window.posthog || {
            capture: function (event, properties) {
                $log.info('[PostHog Event Captured]', event, properties);
            }
        };
        var sentry = $window.Sentry || {
            captureException: function (err) {
                $log.error('[Sentry Error Captured]', err);
            }
        };
        return {
            trackFileUpload: function (filename, size) {
                posthog.capture('Uploaded_File', {
                    filename: filename,
                    byte_size: size,
                    timestamp: new Date().toISOString()
                });
            },
            trackMergedSku: function (parentSku, childSku) {
                posthog.capture('Merged_SKU', {
                    parent_sku: parentSku,
                    child_sku: childSku,
                    timestamp: new Date().toISOString()
                });
            },
            trackIgnoredSku: function (skuA, skuB) {
                posthog.capture('Ignored_SKU', {
                    sku_a: skuA,
                    sku_b: skuB,
                    timestamp: new Date().toISOString()
                });
            },
            logError: function (exception, contextMessage) {
                if (contextMessage) {
                    $log.error(contextMessage, exception);
                }
                sentry.captureException(exception);
            }
        };
    }]);
//# sourceMappingURL=telemetryService.js.map