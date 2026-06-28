declare var angular: any;

angular.module('supplyForgeApp')
.factory('telemetryService', ['$window', '$log', function($window: any, $log: any) {
    
    // Initialize PostHog and Sentry wrappers safely
    var posthog = $window.posthog || {
        capture: function(event: string, properties: any) {
            $log.info('[PostHog Event Captured]', event, properties);
        }
    };

    var sentry = $window.Sentry || {
        captureException: function(err: any) {
            $log.error('[Sentry Error Captured]', err);
        }
    };

    return {
        trackFileUpload: function(filename: string, size: number) {
            posthog.capture('Uploaded_File', {
                filename: filename,
                byte_size: size,
                timestamp: new Date().toISOString()
            });
        },

        trackMergedSku: function(parentSku: string, childSku: string) {
            posthog.capture('Merged_SKU', {
                parent_sku: parentSku,
                child_sku: childSku,
                timestamp: new Date().toISOString()
            });
        },

        trackIgnoredSku: function(skuA: string, skuB: string) {
            posthog.capture('Ignored_SKU', {
                sku_a: skuA,
                sku_b: skuB,
                timestamp: new Date().toISOString()
            });
        },

        logError: function(exception: any, contextMessage?: string) {
            if (contextMessage) {
                $log.error(contextMessage, exception);
            }
            sentry.captureException(exception);
        }
    };
}]);
