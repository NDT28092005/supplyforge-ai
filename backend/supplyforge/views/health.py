from rest_framework.decorators import api_view
from rest_framework.response import Response
from supplyforge.models import Product


@api_view(['GET'])
def ping(request):
    return Response({"service": "supplyforge-ai", "status": "ok"})


@api_view(['GET'])
def check_data(request):
    user_id = request.GET.get('userId', 'user_default_001')
    count = Product.objects.filter(user_id=user_id).count()
    return Response({"hasData": count > 0, "count": count})
