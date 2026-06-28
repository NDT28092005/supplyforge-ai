import json
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt

from .services import DynamicFileImportService, GeminiColumnMappingService

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
    is_async = request.data.get('async', 'false').lower() == 'true'
    
    if not file or not mapping_rule_json:
        return Response({"error": "File hoặc mapping rule bị thiếu."}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        mapping_rule = json.loads(mapping_rule_json)
        
        if is_async:
            try:
                import os, uuid
                from django.conf import settings
                from core.tasks import process_file_import_async
                
                temp_dir = os.path.join(settings.BASE_DIR, 'tmp')
                os.makedirs(temp_dir, exist_ok=True)
                temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{file.name}")
                with open(temp_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)
                        
                task = process_file_import_async.delay(temp_path, mapping_rule, user_id)
                return Response({
                    "message": "File import task accepted for background processing.",
                    "taskId": task.id,
                    "status": "ACCEPTED"
                }, status=status.HTTP_202_ACCEPTED)
            except Exception as async_err:
                print(f"Async Celery dispatch failed ({async_err}). Falling back to sync import.")
                if hasattr(file, 'seek'):
                    file.seek(0)
                DynamicFileImportService.process_batch_import(file, mapping_rule, user_id)
                return Response({"message": "Batch import processed successfully."})
        else:
            if hasattr(file, 'seek'):
                file.seek(0)
            DynamicFileImportService.process_batch_import(file, mapping_rule, user_id)
            return Response({"message": "Batch import processed successfully."})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['GET'])
def get_task_status(request, task_id):
    from celery.result import AsyncResult
    result = AsyncResult(task_id)
    
    response = {
        "taskId": task_id,
        "status": result.status,
    }
    
    if result.status == 'PROCESSING' or result.status == 'PENDING':
        info = result.info if isinstance(result.info, dict) else {}
        response["progress"] = info.get('progress', 0)
        response["message"] = info.get('message', 'Processing...')
    elif result.status == 'SUCCESS':
        response["progress"] = 100
        response["result"] = result.result
    elif result.status == 'FAILURE':
        response["progress"] = 100
        response["error"] = str(result.info)
        
    return Response(response)


@csrf_exempt
@api_view(['DELETE'])
def clear_data(request):
    user_id = request.GET.get('userId', 'user_default_001')
    try:
        DynamicFileImportService.clear_data(user_id)
        return Response({"message": "Đã xóa dữ liệu cũ thành công."})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

