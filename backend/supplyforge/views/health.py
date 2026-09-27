from rest_framework.decorators import api_view
from rest_framework.response import Response
from supplyforge.models import Product, SlowMovingRiskAssessment, Order


@api_view(['GET'])
def ping(request):
    return Response({"service": "supplyforge-ai", "status": "ok"})


@api_view(['GET'])
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
