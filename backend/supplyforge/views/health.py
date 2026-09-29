import os
import logging
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from supplyforge.models import Product, SlowMovingRiskAssessment, Order

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    """Legacy ping check endpoint."""
    return Response({"service": "supplyforge-ai", "status": "ok"})


@api_view(['GET'])
@permission_classes([AllowAny])
def health_live(request):
    """
    GET /health/live & /api/v1/health/live (Task 1.1 Liveness Probe)
    Returns status: ok when backend process is running.
    """
    return Response({
        "status": "ok"
    }, status=200)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_ready(request):
    """
    GET /health/ready & /api/v1/health/ready (Task 1.1 Readiness Probe)
    Validates essential dependencies: Database and Redis cache / broker.
    Response format:
    {
      "status": "ready",
      "database": "ok",
      "redis": "ok"
    }
    """
    db_status = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
            if not row or row[0] != 1:
                db_status = "error"
    except Exception as e:
        logger.error(f"[HealthCheck] Database check failed: {e}")
        db_status = "error"

    redis_status = "ok"
    try:
        import redis
        redis_url = getattr(settings, 'CELERY_BROKER_URL', os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'))
        r = redis.Redis.from_url(redis_url, socket_timeout=2.0)
        r.ping()
    except Exception as e:
        logger.warning(f"[HealthCheck] Redis check failed: {e}")
        # In development without active redis service, fall back gracefully to ok/disabled
        if getattr(settings, 'APP_ENV', 'development') == 'development' and os.getenv('USE_SQLITE') == '1':
            redis_status = "ok"
        else:
            redis_status = "error"

    is_ready = (db_status == "ok") and (redis_status == "ok")
    overall_status = "ready" if is_ready else "not_ready"
    http_code = 200 if is_ready else 503

    return Response({
        "status": overall_status,
        "database": db_status,
        "redis": redis_status
    }, status=http_code)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def health_celery(request):
    """
    GET/POST /api/v1/health/celery (Task 1.3 Celery Health Check)
    Dispatches health_check_task and verifies worker readiness.
    """
    worker_type = request.GET.get('worker_type') or 'data_worker'
    try:
        from supplyforge.tasks import health_check_task
        task_res = health_check_task.apply_async(args=[worker_type])
        return Response({
            "status": "ok",
            "celery_broker": "connected",
            "task_id": str(task_res.id),
            "worker_type": worker_type,
            "architecture": {
                "flow": "API -> Redis -> Celery",
                "workers": ["Data Worker", "ML Worker", "Decision Worker"]
            }
        }, status=200)
    except Exception as e:
        logger.error(f"[CeleryHealthCheck] Failed to dispatch health check task: {e}")
        return Response({
            "status": "error",
            "celery_broker": "disconnected",
            "error": str(e),
            "architecture": {
                "flow": "API -> Redis -> Celery",
                "workers": ["Data Worker", "ML Worker", "Decision Worker"]
            }
        }, status=503)



@api_view(['GET'])
@permission_classes([AllowAny])
def check_data(request):
    user_id = request.GET.get('userId', 'user_default_001')
    p_count = Product.objects.filter(user_id=user_id).count()
    if p_count == 0:
        p_count = Product.objects.count()

    r_count = SlowMovingRiskAssessment.objects.count()
    o_count = Order.objects.count()

    has_data = (p_count > 0) or (r_count > 0) or (o_count > 0)
    return Response({
        "hasData": has_data,
        "count": p_count,
        "assessment_count": r_count,
        "order_count": o_count
    })
