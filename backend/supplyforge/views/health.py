from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from supplyforge.models import Product, SlowMovingRiskAssessment, Order


@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    """Simple ping check for legacy monitoring."""
    return Response({"service": "supplyforge-ai", "status": "ok"})


@api_view(['GET'])
@permission_classes([AllowAny])
def health_live(request):
    """
    LivenessProbe (/health/live):
    Returns HTTP 200 if backend container / web service process is alive.
    """
    return Response({
        "status": "UP",
        "service": "supplyforge-ai",
        "environment": getattr(settings, 'APP_ENV', 'development'),
        "version": getattr(settings, 'APP_VERSION', '1.0.0'),
        "timestamp": timezone.now().isoformat()
    }, status=200)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_ready(request):
    """
    ReadinessProbe (/health/ready):
    Validates essential dependencies (e.g., DB connectivity).
    Returns HTTP 200 if ready to receive traffic, HTTP 503 if dependencies fail.
    """
    db_ok = False
    db_error = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
            if row and row[0] == 1:
                db_ok = True
    except Exception as e:
        db_error = str(e)

    overall_status = "UP" if db_ok else "DOWN"
    http_status = 200 if db_ok else 503

    payload = {
        "status": overall_status,
        "service": "supplyforge-ai",
        "environment": getattr(settings, 'APP_ENV', 'development'),
        "version": getattr(settings, 'APP_VERSION', '1.0.0'),
        "checks": {
            "database": "UP" if db_ok else f"DOWN: {db_error}"
        },
        "timestamp": timezone.now().isoformat()
    }
    return Response(payload, status=http_status)


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
