"""Workspace-scoped inventory evidence coverage API."""

from datetime import date

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from supplyforge.services.inventory_readiness import InventoryReadinessReportService


class InventoryReadinessReportView(APIView):
    """Return snapshot completeness by warehouse; never fill missing values."""

    def get(self, request, *args, **kwargs):
        raw_date = request.query_params.get("as_of")
        try:
            as_of = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
        except ValueError:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_AS_OF_DATE",
                        "message": "as_of phải có định dạng YYYY-MM-DD.",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace_id = int(request.workspace_id) if getattr(request, "tenant_context_validated", False) else 1
        return Response(
            InventoryReadinessReportService.report(workspace_id=workspace_id, as_of=as_of),
            status=status.HTTP_200_OK,
        )
