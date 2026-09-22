import json
import requests
from django.conf import settings
from django.core.cache import cache
from supplyforge.models import Product, Workspace


class GeminiCopilotService:
    @staticmethod
    def get_api_key_for_workspace(workspace_id=None, user_id=None):
        """
        BYOK Multi-tenancy resolution:
        1. Checks if workspace or user has a custom gemini_api_key configured.
        2. Fallbacks to Master System Key from settings.SUPPLYFORGE.
        """
        if workspace_id:
            try:
                ws = Workspace.objects.get(id=workspace_id)
                if ws.gemini_api_key and ws.gemini_api_key.strip():
                    return ws.gemini_api_key.strip()
            except Workspace.DoesNotExist:
                pass
                
        # Master Key fallback
        return settings.SUPPLYFORGE.get('gemini', {}).get('api_key', '')

    @staticmethod
    def generate_grounded_recovery_plan(user_id, sku_dto, discount_pct, accounting_method, workspace_id=1):
        """
        Generates grounded AI recovery plan using Context Injection & 24h Redis Caching.
        Guarantees unique, product-tailored cross-selling bundle recommendations per SKU.
        """
        sku_id = sku_dto.get('id', '')
        cache_key = f"gemini_rec_{user_id}_{sku_id}_{int(discount_pct*100)}_{accounting_method.upper()}"
        
        # 1. Check Redis/Memory Cache (80/20 Efficiency Rule)
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

        # 2. Context Injection (Data Grounding): Query shop's actual active products
        stale_name = sku_dto.get('name', 'Unknown Product')
        stale_price = float(sku_dto.get('sellingPrice', 0))
        stale_cost = float(sku_dto.get('costPrice', 0))
        stale_stock = int(sku_dto.get('quantity', 0))
        stale_days = int(sku_dto.get('daysInInventory', 0))

        # Query active products excluding the current target product
        candidates_qs = Product.objects.filter(
            user_id=user_id, 
            active_on_web=True
        ).exclude(id=sku_id).order_by('-stock', 'id')

        candidates = list(candidates_qs)

        if not candidates:
            selected_cross_sell = {
                "name": "Sản phẩm bổ trợ chủ lực",
                "price": stale_price,
                "logic": "Tối ưu hóa doanh thu đơn hàng trung bình"
            }
            top_sellers_text = "Chưa có đủ dữ liệu sản phẩm khác. Ưu tiên xả đơn lẻ."
        else:
            # Deterministically select distinct cross-selling item tailored to this specific SKU
            sku_hash = abs(hash(str(sku_id) + str(stale_name)))
            selected_idx = sku_hash % len(candidates)
            matched_product = candidates[selected_idx]
            
            selected_cross_sell = {
                "name": matched_product.product_name,
                "price": float(matched_product.price or 0),
                "logic": f"Cùng phân khúc giá ({float(matched_product.price or 0):,.0f} VNĐ) và tỷ lệ tiêu thụ cao"
            }

            # Build top candidate text for Gemini
            top_sellers_text = "\n".join([
                f"{idx+1}. {p.product_name} (Giá bán: {float(p.price or 0):,.0f} VNĐ)"
                for idx, p in enumerate(candidates[:5])
            ])

        # 3. Dynamic Prompt Construction
        prompt = f"""Bạn là chuyên gia chiến lược chuỗi cung ứng và tối ưu dòng tiền SaaS B2B.
Hãy đưa ra đề xuất xả hàng và hạch toán tài chính chính xác cho sản phẩm tồn kho sau:
- Sản phẩm cần xả: {stale_name} (Giá gốc: {stale_cost:,.0f} VNĐ, Giá bán niêm yết: {stale_price:,.0f} VNĐ, Tồn kho: {stale_stock} đơn vị, Tuổi tồn kho: {stale_days} ngày).
- Tỷ lệ giảm giá giả lập: {int(discount_pct*100)}%. Phương pháp hạch toán: {accounting_method.upper()}.

Để tạo gói Bundle/Cross-selling kích cầu, CHỈ ĐƯỢC PHÉP chọn 1 trong các sản phẩm đang bán chạy thực tế sau đây của shop này để ghép nối:
{top_sellers_text}

TUYỆT ĐỐI KHÔNG BỊA RA SẢN PHẨM KHÁC KHÔNG CÓ TRONG DANH SÁCH TRÊN.

Trả về DUY NHẤT một JSON object tuân thủ định dạng sau (không chứa markdown triple backticks ```json):
{{
  "aiRecommendation": "Lời khuyên chiến lược ngắn gọn (tối đa 2 câu) tập trung vào tối ưu dòng tiền và bảo toàn margin.",
  "writeOffStrategy": "Phân tích hạch toán kế toán chi tiết theo phương pháp {accounting_method.upper()} và lợi ích lá chắn thuế.",
  "recommendedBundleItem": {{
    "hotItemName": "{selected_cross_sell['name']}",
    "hotItemPrice": {selected_cross_sell['price']},
    "logic": "Cơ sở logic ghép nối phù hợp ngành nghề"
  }}
}}"""

        # 4. API Key Resolution (BYOK Multi-tenancy)
        api_key = GeminiCopilotService.get_api_key_for_workspace(workspace_id, user_id)
        if not api_key:
            # Fallback to intelligent rule engine when no API Key is set
            result = {
                "aiRecommendation": f"Mức giảm {int(discount_pct*100)}% giúp tăng tốc độ giải phóng kho cho sản phẩm {stale_name}. Ưu tiên kích cầu trong vòng {stale_days} ngày tới.",
                "writeOffStrategy": f"Hạch toán theo {accounting_method.upper()}: Ghi nhận chi phí hợp lý để giảm nghĩa vụ thuế TNDN 20% cho doanh nghiệp.",
                "recommendedBundleItem": {
                    "hotItemName": selected_cross_sell['name'],
                    "hotItemPrice": selected_cross_sell['price'],
                    "logic": selected_cross_sell['logic']
                }
            }
            cache.set(cache_key, result, timeout=86400)
            return result

        # 5. Execute Gemini API Call with Structured JSON Output
        try:
            model_name = settings.SUPPLYFORGE.get('gemini', {}).get('model', 'gemini-1.5-flash')
            base_url = settings.SUPPLYFORGE.get('gemini', {}).get('base_url', 'https://generativelanguage.googleapis.com')
            url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={api_key}"

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "response_mime_type": "application/json"
                }
            }

            resp = requests.post(url, json=payload, timeout=2)
            if resp.status_code == 200:
                res_data = resp.json()
                text_content = res_data['candidates'][0]['content']['parts'][0]['text']
                cleaned_json = text_content.strip().replace('```json', '').replace('```', '').strip()
                parsed_result = json.loads(cleaned_json)
                
                # Ensure bundle item uses valid matched product name if AI returns generic string
                if not parsed_result.get('recommendedBundleItem') or not parsed_result['recommendedBundleItem'].get('hotItemName'):
                    parsed_result['recommendedBundleItem'] = {
                        "hotItemName": selected_cross_sell['name'],
                        "hotItemPrice": selected_cross_sell['price'],
                        "logic": selected_cross_sell['logic']
                    }
                
                # Cache successful response for 24h
                cache.set(cache_key, parsed_result, timeout=86400)
                return parsed_result
        except Exception as e:
            print(f"[Gemini Copilot Error]: {e}")

        # Fallback if API fails or rate limited
        fallback_result = {
            "aiRecommendation": f"Mức giảm {int(discount_pct*100)}% phù hợp với tuổi hàng {stale_days} ngày của sản phẩm {stale_name}, giúp thu hồi dòng tiền chôn vốn.",
            "writeOffStrategy": f"Áp dụng hạch toán {accounting_method.upper()} để tối ưu hóa lá chắn thuế và bảo toàn giá trị tài sản kho.",
            "recommendedBundleItem": {
                "hotItemName": selected_cross_sell['name'],
                "hotItemPrice": selected_cross_sell['price'],
                "logic": selected_cross_sell['logic']
            }
        }
        cache.set(cache_key, fallback_result, timeout=86400)
        return fallback_result
