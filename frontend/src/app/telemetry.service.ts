import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class TelemetryService {
  private posthog = (window as any).posthog || {
    capture: (event: string, properties: any) => {
      console.info('[PostHog Event Captured]', event, properties);
    }
  };

  private sentry = (window as any).Sentry || {
    captureException: (err: any) => {
      console.error('[Sentry Error Captured]', err);
    }
  };

  trackFileUpload(filename: string, size: number): void {
    this.posthog.capture('Uploaded_File', {
      filename,
      byte_size: size,
      timestamp: new Date().toISOString()
    });
  }

  trackMergedSku(parentSku: string, childSku: string): void {
    this.posthog.capture('Merged_SKU', {
      parent_sku: parentSku,
      child_sku: childSku,
      timestamp: new Date().toISOString()
    });
  }

  trackIgnoredSku(skuA: string, skuB: string): void {
    this.posthog.capture('Ignored_SKU', {
      sku_a: skuA,
      sku_b: skuB,
      timestamp: new Date().toISOString()
    });
  }

  logError(exception: any, contextMessage?: string): void {
    if (contextMessage) {
      console.error(contextMessage, exception);
    }
    this.sentry.captureException(exception);
  }
}
