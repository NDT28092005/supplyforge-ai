import json
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.services.ingestion import DynamicFileImportService, GeminiColumnMappingService


@csrf_exempt
@api_view(['POST'])
def analyze_file(request):
    file = request.FILES.get('file')
    if not file:
        return Response({"error": "File upload không hợp lệ hoặc rỗng."}, status=status.HTTP_400_BAD_REQUEST)
        
    if not file.name.lower().endswith('.csv'):
        return Response({"error": "Hệ thống hiện tại chỉ hỗ trợ trích xuất luồng Streaming cho file CSV."}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        headers, sample_rows = DynamicFileImportService.peek_sample_data(file)
        ai_suggestions = GeminiColumnMappingService.infer_column_mapping(headers, sample_rows)
        
        response = {
            "headers": headers,
            "sampleData": sample_rows[0] if sample_rows else None,
            "aiSuggestions": ai_suggestions
        }
        return Response(response)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['POST'])
def process_file(request):
    file = request.FILES.get('file')
    mapping_rule_json = request.data.get('mappingRule')
    user_id = request.data.get('userId', 'user_default_001')
    
    if not file or not mapping_rule_json:
        return Response({"error": "File hoặc mapping rule bị thiếu."}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        mapping_rule = json.loads(mapping_rule_json)
        DynamicFileImportService.process_batch_import(file, mapping_rule, user_id)
        return Response({"message": "Batch import processed successfully."})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['DELETE'])
def clear_data(request):
    user_id = request.GET.get('userId', 'user_default_001')
    try:
        DynamicFileImportService.clear_data(user_id)
        return Response({"message": "Đã xóa dữ liệu cũ thành công."})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
