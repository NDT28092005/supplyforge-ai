"""
REST API Views for ACT-001 & ACT-002 Action Plan & Status Management.
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from supplyforge.models.action_plan import ActionPlanRecord
import datetime


class ActionPlanListCreateView(APIView):
    """
    POST /api/v1/action-plans/: ACT-001 Create Action Plan.
    GET /api/v1/action-plans/: List Action Plans.
    """

    def post(self, request, *args, **kwargs):
        data = request.data or {}
        campaign_name = data.get("campaign_name") or data.get("campaign")
        sku = data.get("sku") or "UNKNOWN_SKU"

        if not campaign_name:
            campaign_name = f"Clearance {sku}"

        duration_days = int(data.get("duration_days") or data.get("duration") or 14)
        strategy = str(data.get("strategy") or "15% discount")
        owner = str(data.get("owner") or "Merchant")
        start_date_raw = data.get("start_date") or data.get("start") or datetime.date.today().isoformat()

        # Format start_date
        try:
            if isinstance(start_date_raw, datetime.date):
                start_date = start_date_raw
            else:
                start_date = datetime.datetime.strptime(str(start_date_raw).split("T")[0], "%Y-%m-%d").date()
        except Exception:
            start_date = datetime.date.today()

        action_status = data.get("status", "DRAFT").upper()
        valid_statuses = ["DRAFT", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
        if action_status not in valid_statuses:
            action_status = "DRAFT"

        plan = ActionPlanRecord.objects.create(
            campaign_name=campaign_name,
            sku=sku,
            duration_days=duration_days,
            strategy=strategy,
            owner=owner,
            start_date=start_date,
            status=action_status,
            decision_id=data.get("decision_id"),
            notes=data.get("notes", ""),
            expected_recovery_value=int(data.get("expected_recovery_value") or data.get("expected_recovery") or 12000000),
            expected_units_sold=int(data.get("expected_units_sold") or data.get("expected_units") or 100),
            actual_recovery_value=data.get("actual_recovery_value") or data.get("actual_recovery"),
            actual_units_sold=data.get("actual_units_sold") or data.get("actual_units")
        )

        return Response({
            "success": True,
            "plan_id": plan.plan_id,
            "campaign": plan.campaign_name,
            "campaign_name": plan.campaign_name,
            "sku": plan.sku,
            "duration": f"{plan.duration_days} days",
            "duration_days": plan.duration_days,
            "strategy": plan.strategy,
            "owner": plan.owner,
            "start": plan.start_date.isoformat(),
            "start_date": plan.start_date.isoformat(),
            "status": plan.status,
            "expected_recovery_value": plan.expected_recovery_value,
            "actual_recovery_value": plan.actual_recovery_value,
            "expected_units_sold": plan.expected_units_sold,
            "actual_units_sold": plan.actual_units_sold,
            "created_at": plan.created_at.isoformat()
        }, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        sku = request.query_params.get("sku")
        status_param = request.query_params.get("status")
        owner = request.query_params.get("owner")

        qs = ActionPlanRecord.objects.all()
        if sku:
            qs = qs.filter(sku=sku)
        if status_param and status_param.upper() != "ALL":
            qs = qs.filter(status=status_param.upper())
        if owner:
            qs = qs.filter(owner__icontains=owner)

        plans = []
        for p in qs:
            rec_acc = round((p.actual_recovery_value / p.expected_recovery_value) * 100, 1) if (p.actual_recovery_value is not None and p.expected_recovery_value > 0) else None
            unit_acc = round((p.actual_units_sold / p.expected_units_sold) * 100, 1) if (p.actual_units_sold is not None and p.expected_units_sold > 0) else None

            plans.append({
                "plan_id": p.plan_id,
                "campaign": p.campaign_name,
                "campaign_name": p.campaign_name,
                "sku": p.sku,
                "duration": f"{p.duration_days} days",
                "duration_days": p.duration_days,
                "strategy": p.strategy,
                "owner": p.owner,
                "start": p.start_date.isoformat(),
                "start_date": p.start_date.isoformat(),
                "status": p.status,
                "confirmed_by": p.confirmed_by,
                "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
                "expected_recovery_value": p.expected_recovery_value,
                "actual_recovery_value": p.actual_recovery_value,
                "expected_units_sold": p.expected_units_sold,
                "actual_units_sold": p.actual_units_sold,
                "recovery_accuracy_pct": rec_acc,
                "units_accuracy_pct": unit_acc,
                "notes": p.notes,
                "created_at": p.created_at.isoformat()
            })

        return Response(plans, status=status.HTTP_200_OK)


class ActionPlanStatusUpdateView(APIView):
    """
    PATCH /api/v1/action-plans/<plan_id>/status/: ACT-002 & ACT-003 Update Action Status & Confirmation Gate.
    """

    def patch(self, request, plan_id, *args, **kwargs):
        try:
            plan = ActionPlanRecord.objects.get(plan_id=plan_id)
        except ActionPlanRecord.DoesNotExist:
            return Response(
                {"success": False, "error": {"code": "PLAN_NOT_FOUND", "message": f"Action plan {plan_id} not found."}},
                status=status.HTTP_404_NOT_FOUND
            )

        new_status = (request.data.get("status") or "").upper()
        valid_statuses = ["DRAFT", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]

        if new_status not in valid_statuses:
            return Response(
                {"success": False, "error": {"code": "INVALID_STATUS", "message": f"Status must be one of {valid_statuses}."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ACT-003 Merchant Confirmation tracking
        if new_status == "CONFIRMED" and plan.status != "CONFIRMED":
            import django.utils.timezone
            plan.confirmed_by = request.data.get("confirmed_by") or request.data.get("actor") or "Merchant"
            plan.confirmed_at = django.utils.timezone.now()

        plan.status = new_status
        if "notes" in request.data:
            plan.notes = request.data["notes"]
        plan.save()

        return Response({
            "success": True,
            "plan_id": plan.plan_id,
            "campaign": plan.campaign_name,
            "status": plan.status,
            "confirmed_by": plan.confirmed_by,
            "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
            "updated_at": plan.updated_at.isoformat()
        }, status=status.HTTP_200_OK)


class ActionPlanOutcomeView(APIView):
    """
    PATCH /api/v1/action-plans/<plan_id>/outcome/: ACT-004 Record Outcome & Evaluate Decision Usefulness.
    """

    def patch(self, request, plan_id, *args, **kwargs):
        try:
            plan = ActionPlanRecord.objects.get(plan_id=plan_id)
        except ActionPlanRecord.DoesNotExist:
            return Response(
                {"success": False, "error": {"code": "PLAN_NOT_FOUND", "message": f"Action plan {plan_id} not found."}},
                status=status.HTTP_404_NOT_FOUND
            )

        data = request.data or {}
        if "actual_recovery_value" in data or "actual_recovery" in data:
            plan.actual_recovery_value = int(data.get("actual_recovery_value") or data.get("actual_recovery"))
        if "actual_units_sold" in data or "actual_units" in data:
            plan.actual_units_sold = int(data.get("actual_units_sold") or data.get("actual_units"))
        if "expected_recovery_value" in data or "expected_recovery" in data:
            plan.expected_recovery_value = int(data.get("expected_recovery_value") or data.get("expected_recovery"))
        if "expected_units_sold" in data or "expected_units" in data:
            plan.expected_units_sold = int(data.get("expected_units_sold") or data.get("expected_units"))

        import django.utils.timezone
        plan.outcome_recorded_at = django.utils.timezone.now()
        plan.save()

        rec_acc = round((plan.actual_recovery_value / plan.expected_recovery_value) * 100, 1) if (plan.actual_recovery_value is not None and plan.expected_recovery_value > 0) else 0.0
        unit_acc = round((plan.actual_units_sold / plan.expected_units_sold) * 100, 1) if (plan.actual_units_sold is not None and plan.expected_units_sold > 0) else 0.0

        usefulness_score = "HIGH" if rec_acc >= 75 and unit_acc >= 75 else ("MEDIUM" if rec_acc >= 50 else "LOW")

        return Response({
            "success": True,
            "plan_id": plan.plan_id,
            "outcome": {
                "expected_recovery_value": plan.expected_recovery_value,
                "actual_recovery_value": plan.actual_recovery_value,
                "recovery_accuracy_pct": rec_acc,
                "expected_units_sold": plan.expected_units_sold,
                "actual_units_sold": plan.actual_units_sold,
                "units_accuracy_pct": unit_acc,
                "decision_usefulness": usefulness_score
            }
        }, status=status.HTTP_200_OK)

