from django.urls import path
from . import views

urlpatterns = [
    path('api/v1/import/analyze', views.analyze_file, name='analyze_file'),
    path('api/v1/import/process', views.process_file, name='process_file'),
    path('api/v1/import/task/<str:task_id>', views.get_task_status, name='get_task_status'),
    path('api/v1/import/clear', views.clear_data, name='clear_data'),
]
