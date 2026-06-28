from django.urls import path
from . import views

urlpatterns = [
    path('api/v1/workspaces/<int:workspace_id>/dashboard/portfolio-command', views.get_portfolio_command, name='get_portfolio_command'),
    path('api/v1/workspaces/<int:workspace_id>/dashboard/financial-analysis', views.get_financial_analysis, name='get_financial_analysis'),
]
