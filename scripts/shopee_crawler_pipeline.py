import os
import time
import random
import requests
import logging
from datetime import datetime, timedelta

# Import Django backend tools if run inside Django context, otherwise use dummy fallback
try:
    from django.conf import settings
    from supplyforge.models import Product, Order, OrderItem
    from supplyforge.services.shopee_client import ShopeeClient
    from celery import shared_task
    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    shared_task = lambda func: func  # Dummy decorator

logger = logging.getLogger(__name__)


# =====================================================================
# STRATEGY 1: Official Shopee API Continuous Delta Sync (Phase 1-3)
# =====================================================================

@shared_task
def run_continuous_shopee_sync_task(shop_id, workspace_id=1):
    """
    Continuous background worker (triggered via Celery Beat every 30-60 mins).
    Syncs new/updated products and orders incrementally to feed the ML dataset.
    """
    print(f"\n--- [CRAWLER] Starting Shopee Official API Sync for Shop {shop_id} ---")
    if not DJANGO_AVAILABLE:
        print("Django/Celery not loaded. Simulating API delta sync workflow.")
        return

    # 1. Fetch connection from DB
    from supplyforge.models import ShopeeConnection  # Assuming this exists
    try:
        connection = ShopeeConnection.objects.get(shop_id=shop_id)
    except Exception:
        logger.error(f"No Shopee connection found for shop_id {shop_id}")
        return

    client = ShopeeClient(connection)
    
    # Calculate time window (e.g. sync changes from last 2 hours to avoid missing updates)
    time_to = int(time.time())
    time_from = time_to - (2 * 3600)  # 2 hours ago

    # 2. Sync Products
    try:
        print("Fetching updated product list from Shopee...")
        item_list_resp = client.get_item_list(update_time_from=time_from, update_time_to=time_to)
        item_ids = [item['item_id'] for item in item_list_resp.get('response', {}).get('item_list', [])]
        
        if item_ids:
            print(f"Updating {len(item_ids)} products in DB...")
            details = client.get_item_detail_chunked(item_ids)
            for item in details:
                # Update or create Product records in SupplyForge DB
                Product.objects.update_or_create(
                    third_party_id=str(item['item_id']),
                    user_id=connection.user_id,
                    defaults={
                        'product_name': item.get('item_name'),
                        'item_sku': item.get('item_sku', ''),
                        'price': item.get('price_info', [{}])[0].get('original_price', 0.0),
                        'stock': item.get('stock_info', [{}])[0].get('normal_stock', 0),
                        'platform': 'shopee',
                        'updated_at': timezone.now()
                    }
                )
    except Exception as e:
        logger.error(f"Error syncing products: {e}")

    # 3. Sync Orders
    try:
        print("Fetching updated orders from Shopee...")
        order_list_resp = client.get_order_list(time_from=time_from, time_to=time_to)
        orders_sn = [order['order_sn'] for order in order_list_resp.get('response', {}).get('order_list', [])]
        
        if orders_sn:
            print(f"Updating {len(orders_sn)} order records in DB...")
            order_details = client.get_order_detail(orders_sn).get('response', {}).get('order_list', [])
            for order_data in order_details:
                # Update or create Order records
                order_obj, _ = Order.objects.update_or_create(
                    order_id=order_data['order_sn'],
                    user_id=connection.user_id,
                    defaults={
                        'amount': order_data.get('total_amount', 0.0),
                        'platform': 'shopee',
                        'created_at': datetime.fromtimestamp(order_data['create_time']),
                        'updated_at': timezone.now()
                    }
                )
                
                # Update items
                for item in order_data.get('item_list', []):
                    OrderItem.objects.update_or_create(
                        order=order_obj,
                        item_id=str(item['item_id']),
                        sku=item.get('item_sku', ''),
                        defaults={
                            'product_name': item.get('item_name'),
                            'quantity': item.get('model_quantity_purchased', 1),
                            'price': item.get('model_original_price', 0.0)
                        }
                    )
    except Exception as e:
        logger.error(f"Error syncing orders: {e}")


# =====================================================================
# STRATEGY 2: Public Shopee Category / Competitor Scraper (Market Data)
# =====================================================================

class PublicShopeeScraper:
    """
    Public crawler to scrape product listings and prices from search categories.
    Used to gather competitor pricing dataset to calculate relative price indexes.
    
    Warning: Public crawlers must respect Shopee's rate limits and bypass anti-crawling
    by rotating User-Agents and using random sleep delays.
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
    ]

    def __init__(self, keyword, site_url="https://shopee.vn"):
        self.keyword = keyword
        self.site_url = site_url
        self.session = requests.Session()

    def get_headers(self):
        """Build headers mimicking real browser behavior."""
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.site_url}/search?keyword={self.keyword}",
            "X-Requested-With": "XMLHttpRequest",
        }

    def scrape_search_results(self, limit=50):
        """
        Scrapes search listings via Shopee's internal endpoint.
        Returns a list of dictionaries with product metadata.
        """
        print(f"\n--- [CRAWLER] Scraping public market listings for keyword: '{self.keyword}' ---")
        
        # Shopee's internal search API endpoint
        api_url = f"{self.site_url}/api/v4/search/search_items"
        
        params = {
            "by": "relevancy",
            "keyword": self.keyword,
            "limit": limit,
            "newest": 0,
            "order": "desc",
            "page_type": "search",
            "scenario": "PAGE_GLOBAL_SEARCH",
            "version": "2"
        }

        try:
            # Rotate headers and simulate random latency (1.5s to 4s) to avoid bot detection
            time.sleep(random.uniform(1.5, 4.0))
            
            headers = self.get_headers()
            resp = self.session.get(api_url, headers=headers, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('item_basic', []) or data.get('items', [])
                
                market_data = []
                for item in items:
                    # In some responses the item_basic is nested
                    ib = item.get('item_basic') if 'item_basic' in item else item
                    
                    if not ib:
                        continue
                        
                    name = ib.get('name')
                    price_raw = ib.get('price') # In micro-VND (price * 100k)
                    price = float(price_raw) / 100000.0 if price_raw else 0.0
                    stock = ib.get('stock')
                    sold = ib.get('historical_sold') or ib.get('sold', 0)
                    rating = ib.get('item_rating', {}).get('rating_star', 0.0)

                    market_data.append({
                        "shopee_item_id": ib.get('itemid'),
                        "shopee_shop_id": ib.get('shopid'),
                        "product_name": name,
                        "price": price,
                        "stock": stock,
                        "historical_sold": sold,
                        "rating": rating,
                        "scraped_at": datetime.now().isoformat()
                    })
                
                print(f"Scraped {len(market_data)} competitor product items.")
                return market_data
            else:
                print(f"Failed to scrape: HTTP {resp.status_code}. Anti-bot block may be active.")
                return []
        except Exception as e:
            print(f"Error occurred while scraping search: {e}")
            return []


# =====================================================================
# PIPELINE DEMO EXECUTION
# =====================================================================

if __name__ == "__main__":
    # Test public crawler for a specific retail category (e.g. fashion/t-shirts)
    scraper = PublicShopeeScraper("ao thun polo nam")
    results = scraper.scrape_search_results(limit=10)
    
    if results:
        # Save results to a CSV file to be fed into the data engineering master pipeline
        import pandas as pd
        df = pd.DataFrame(results)
        output_file = "/home/nguyen-dai-tung/supplyforge-ai/test-data/Database - NCKH/shopee_market_scraped.csv"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        df.to_csv(output_file, index=False)
        print(f"Saved market competitor data to: {output_file}")
    else:
        print("Crawler returned empty results. (Possible IP rate limiting or captcha challenge).")
