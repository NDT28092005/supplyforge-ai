"""
REST API Views for Task M6-10 Decision API & Persistence.
Module 06: Decision Support & Capital Recovery Engine

Provides REST endpoints:
- POST /api/v1/decisions/: Persist recommendation & explanation.
- GET /api/v1/decisions/: List decisions with filtering.
- GET /api/v1/decisions/{decision_id}/: Retrieve full decision contract.
- PATCH /api/v1/decisions/{decision_id}/status/: Update decision status & log audit.
- GET /api/v1/decisions/{decision_id}/history/: Retrieve audit timeline.
- GET /api/v1/decisions/{decision_id}/explanation/: Retrieve explanation payload & evidence.
"""

import base64
import binascii
import json
import math

from django.db.models import Q, Sum
from django.utils.dateparse import parse_datetime
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from supplyforge.models import InventoryRecord, SlowMovingRiskAssessment
from supplyforge.models.decision import DecisionRecord, DecisionExplanationRecord
from supplyforge.serializers.decision_serializer import (
    DecisionSerializer, DecisionExplanationSerializer,
    DecisionAuditEventSerializer, DecisionStatusUpdateSerializer,
)
from supplyforge.services.decision_service import (
    DecisionPersistenceService, DecisionStatusService, DecisionHistoryService,
    InvalidStatusTransitionError, DecisionNotFoundError,
)
from supplyforge.services.model_runtime_guard import execution_runtime_status
from supplyforge.services.decision_portfolio_service import (
    DecisionPortfolioService, PortfolioInputError,
)
from supplyforge.services.decision_trust_report import DecisionTrustReportService
from supplyforge.services.decision_revalidation import (
    DecisionRevalidationError, DecisionRevalidationService,
)
from supplyforge.services.weekly_action_planning import (
    WeeklyActionInputError, WeeklyActionPlanningService,
)


def _decision_is_visible_to_request(request, decision):
    """Check the persisted workspace scope of a decision record."""
    if not getattr(request, "tenant_context_validated", False):
        return True
    return decision.workspace_id == request.workspace_id


def _decision_queryset_for_request(request, queryset):
    if not getattr(request, "tenant_context_validated", False):
        return queryset
    return queryset.filter(workspace_id=request.workspace_id)


def _positive_query_int(value, *, default: int, maximum: int, field_name: str) -> int:
    if value in (None, ''):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} must be a positive integer.') from exc
    if parsed < 1:
        raise ValueError(f'{field_name} must be greater than zero.')
    return min(parsed, maximum)


class DecisionCursorError(ValueError):
    pass


_CURSOR_SORTS = {
    'priority': ('priority_score', 'created_at'),
    'capital': ('capital_exposure', 'created_at'),
    'recovery': ('expected_recovery_value', 'created_at'),
    'risk': ('risk_score', 'created_at'),
}


def _encode_decision_cursor(*, sort: str, row: DecisionRecord) -> str:
    metric, timestamp = _CURSOR_SORTS[sort]
    payload = {
        'v': 1, 'sort': sort, 'metric': getattr(row, metric),
        'created_at': getattr(row, timestamp).isoformat(), 'decision_id': row.decision_id,
    }
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode('utf-8')).decode('ascii').rstrip('=')


def _decode_decision_cursor(value: str, *, sort: str) -> dict:
    try:
        padded = str(value) + '=' * (-len(str(value)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise DecisionCursorError('Cursor không hợp lệ.') from exc
    if not isinstance(payload, dict) or payload.get('v') != 1 or payload.get('sort') != sort:
        raise DecisionCursorError('Cursor không phù hợp với thứ tự sắp xếp hiện tại.')
    try:
        metric = float(payload['metric'])
        created_at = parse_datetime(str(payload['created_at']))
        decision_id = str(payload['decision_id'])
    except (KeyError, TypeError, ValueError) as exc:
        raise DecisionCursorError('Cursor không đầy đủ.') from exc
    if created_at is None or not decision_id:
        raise DecisionCursorError('Cursor không đầy đủ.')
    return {'metric': metric, 'created_at': created_at, 'decision_id': decision_id}


def _after_decision_cursor(queryset, *, sort: str, cursor: dict):
    """Apply a stable descending keyset predicate with ID as final tie-break."""
    metric, timestamp = _CURSOR_SORTS[sort]
    return queryset.filter(
        Q(**{f'{metric}__lt': cursor['metric']})
        | Q(**{metric: cursor['metric']}) & Q(**{f'{timestamp}__lt': cursor['created_at']})
        | Q(**{metric: cursor['metric'], timestamp: cursor['created_at'], 'decision_id__gt': cursor['decision_id']})
    )


class DecisionListCreateView(APIView):
    """
    POST /api/v1/decisions/: Persist a new recommendation and explanation.
    GET /api/v1/decisions/: List decisions with filtering.
    """

    def post(self, request, *args, **kwargs):
        payload = request.data
        if not payload or ("recommendation" not in payload and "sku" not in payload):
            return Response(
                {"success": False, "error": {"code": "INVALID_DECISION", "message": "Missing recommendation or SKU payload."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        recommendation = payload.get("recommendation") or payload
        explanation = payload.get("explanation")
        dataset_version = payload.get("dataset_version", "v1.0")

        try:
            decision = DecisionPersistenceService.persist_decision(
                recommendation=recommendation,
                explanation=explanation,
                dataset_version=dataset_version,
                workspace_id=request.workspace_id if getattr(request, "tenant_context_validated", False) else None,
            )
            serializer = DecisionSerializer(decision)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"success": False, "error": {"code": "INVALID_DECISION", "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST
            )

    def get(self, request, *args, **kwargs):
        risk_class = request.query_params.get("risk_class")
        priority = request.query_params.get("priority")
        action_type = request.query_params.get("action_type")
        status_param = request.query_params.get("status")
        sku = request.query_params.get("sku")
        dataset_version = request.query_params.get("dataset_version")
        include_superseded = str(request.query_params.get('include_superseded') or '').lower() in {'1', 'true', 'yes'}
        projection_status = str(request.query_params.get("projection_status") or "").strip()
        search = str(request.query_params.get('q') or '').strip()
        sort = str(request.query_params.get('sort') or 'priority').lower()

        queryset = DecisionPersistenceService.list_decisions(
            risk_class=risk_class,
            priority=priority,
            action_type=action_type,
            status=status_param,
            sku=sku,
            dataset_version=dataset_version,
            workspace_id=request.workspace_id if getattr(request, "tenant_context_validated", False) else None,
            include_superseded=include_superseded,
        )
        queryset = _decision_queryset_for_request(request, queryset)

        # The inbox must be able to surface blocked decisions across all
        # pages. New decisions use a typed indexed projection field. Legacy
        # rows get a narrow compatibility branch until a backfill retires
        # their JSON snapshot filter; no new high-volume rows enter it.
        if projection_status:
            queryset = queryset.filter(
                Q(projection_status=projection_status)
                | Q(
                    projection_status='LEGACY_UNVERIFIED',
                    action_parameters__projection__status=projection_status,
                )
            )

        if search:
            queryset = queryset.filter(
                Q(sku__icontains=search)
                | Q(decision_id__icontains=search)
                | Q(action_type__icontains=search)
            )
        ordering = {
            'priority': ('-priority_score', '-created_at', 'decision_id'),
            'capital': ('-capital_exposure', '-created_at', 'decision_id'),
            'recovery': ('-expected_recovery_value', '-created_at', 'decision_id'),
            'risk': ('-risk_score', '-created_at', 'decision_id'),
        }.get(sort, ('-priority_score', '-created_at', 'decision_id'))
        if sort not in _CURSOR_SORTS:
            sort = 'priority'
        queryset = queryset.order_by(*ordering)

        # Cursor mode is the operational Decision Center's default. It avoids
        # COUNT(*) and increasingly expensive OFFSET scans as a merchant's
        # decision history grows. The old numbered API remains for legacy
        # clients during migration only.
        if str(request.query_params.get('pagination') or '').lower() == 'cursor':
            try:
                page_size = _positive_query_int(request.query_params.get('page_size'), default=20, maximum=100, field_name='page_size')
                cursor_value = request.query_params.get('cursor')
                if cursor_value:
                    queryset = _after_decision_cursor(
                        queryset, sort=sort,
                        cursor=_decode_decision_cursor(cursor_value, sort=sort),
                    )
            except (ValueError, DecisionCursorError) as exc:
                return Response({'success': False, 'error': {'code': 'INVALID_CURSOR', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
            rows = list(queryset[:page_size + 1])
            has_next = len(rows) > page_size
            rows = rows[:page_size]
            return Response({
                'items': DecisionSerializer(rows, many=True).data,
                'pagination': {
                    'mode': 'cursor', 'page_size': page_size, 'has_next': has_next,
                    'next_cursor': _encode_decision_cursor(sort=sort, row=rows[-1]) if has_next and rows else None,
                },
            }, status=status.HTTP_200_OK)

        # Existing API consumers receive the original array unless they opt in
        # to page controls. The operations dashboard always opts in.
        if 'page' not in request.query_params and 'page_size' not in request.query_params:
            serializer = DecisionSerializer(queryset, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        try:
            page = _positive_query_int(request.query_params.get('page'), default=1, maximum=1_000_000, field_name='page')
            page_size = _positive_query_int(request.query_params.get('page_size'), default=20, maximum=100, field_name='page_size')
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_PAGINATION', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        total = queryset.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        serializer = DecisionSerializer(queryset[start:start + page_size], many=True)
        return Response({
            'items': serializer.data,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_items': total,
                'total_pages': total_pages,
                'has_previous': page > 1,
                'has_next': page < total_pages,
            },
        }, status=status.HTTP_200_OK)


class DecisionRecommendationRefreshView(APIView):
    """Rebuild replaceable recommendations from the workspace's latest assessments."""

    def post(self, request, *args, **kwargs):
        if not (
            getattr(request, "tenant_context_validated", False)
            and getattr(request, "workspace_id", None)
        ):
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "UNAUTHENTICATED",
                        "message": "Yêu cầu cần Authorization Bearer token và workspace hợp lệ.",
                    },
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        from supplyforge.services.auto_decision_generator import AutoDecisionGeneratorService

        decisions = AutoDecisionGeneratorService.generate_decisions_from_assessments(
            workspace_id=int(request.workspace_id),
        )
        return Response({
            "success": True,
            "generated_count": len(decisions),
            "message": "Đã cập nhật khuyến nghị từ dữ liệu đánh giá rủi ro hiện có.",
        }, status=status.HTTP_200_OK)


class DecisionPortfolioQueueView(APIView):
    """Create/read an auditable capacity and campaign-budget queue.

    This endpoint is intentionally workspace-authenticated even though a few
    legacy decision endpoints still support unauthenticated development
    fixtures.  Portfolio constraints reveal operational capacity and spending
    intent, so they must never fall back to workspace 1.
    """

    @staticmethod
    def _workspace_or_error(request):
        if not (
            getattr(request, 'tenant_context_validated', False)
            and getattr(request, 'workspace_id', None)
        ):
            return None, Response(
                {'success': False, 'error': {'code': 'UNAUTHENTICATED', 'message': 'Cần workspace đã xác thực để lập danh mục hành động.'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return int(request.workspace_id), None

    def get(self, request, *args, **kwargs):
        workspace_id, error = self._workspace_or_error(request)
        if error:
            return error
        payload = DecisionPortfolioService.latest(workspace_id=workspace_id)
        if not payload:
            return Response({
                'status': 'NOT_GENERATED',
                'message': 'Chưa có danh mục hành động. Hãy khai báo năng lực/ngân sách và tạo một lần chạy mới.',
            }, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)

    def post(self, request, *args, **kwargs):
        workspace_id, error = self._workspace_or_error(request)
        if error:
            return error
        try:
            payload = DecisionPortfolioService.build(
                workspace_id=workspace_id,
                config=(request.data or {}).get('constraints', request.data or {}),
            )
        except PortfolioInputError as exc:
            return Response(
                {'success': False, 'error': {'code': 'INVALID_PORTFOLIO_CONSTRAINTS', 'message': str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(payload, status=status.HTTP_201_CREATED)


class WeeklyActionPlanView(APIView):
    """Expose an owner-aware operating week derived from an audited portfolio."""

    @staticmethod
    def _workspace_or_error(request):
        if not (
            getattr(request, 'tenant_context_validated', False)
            and getattr(request, 'workspace_id', None)
        ):
            return None, Response(
                {'success': False, 'error': {'code': 'UNAUTHENTICATED', 'message': 'Cần workspace đã xác thực để xem hoặc tạo kế hoạch tuần.'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return int(request.workspace_id), None

    def get(self, request, *args, **kwargs):
        workspace_id, error = self._workspace_or_error(request)
        if error:
            return error
        payload = WeeklyActionPlanningService.latest(workspace_id=workspace_id)
        if not payload:
            return Response(
                {'success': False, 'error': {'code': 'WEEKLY_PLAN_NOT_FOUND', 'message': 'Chưa có kế hoạch tuần. Hãy lập danh mục hành động trước.'}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payload)

    def post(self, request, *args, **kwargs):
        workspace_id, error = self._workspace_or_error(request)
        if error:
            return error
        actor = str(request.data.get('actor') or getattr(request, 'user_email', None) or 'merchant')[:128]
        try:
            payload = WeeklyActionPlanningService.create(
                workspace_id=workspace_id, actor=actor, config=request.data or {},
            )
        except WeeklyActionInputError as exc:
            return Response(
                {'success': False, 'error': {'code': 'INVALID_WEEKLY_PLAN', 'message': str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'success': True, **payload}, status=status.HTTP_201_CREATED)


class DecisionSummaryView(APIView):
    """Return portfolio-level operational totals independent of list paging.

    The queue is paginated, so calculating headline capital figures from rows
    currently visible in a browser is misleading.  This endpoint deliberately
    reports only persisted, workspace-scoped decision evidence.
    """

    PRICE_ACTIONS = {'DISCOUNT', 'CLEARANCE', 'PROMOTION'}
    HIGH_RISK_CLASSES = {'CRITICAL', 'HIGH_RISK'}

    def get(self, request, *args, **kwargs):
        queryset = _decision_queryset_for_request(
            request, DecisionRecord.objects.exclude(status='SUPERSEDED'),
        )
        high_risk = queryset.filter(risk_class__in=self.HIGH_RISK_CLASSES)
        projections = high_risk.filter(
            action_type__in=self.PRICE_ACTIONS,
            expected_recovery_value__gt=0,
        )
        totals = high_risk.aggregate(
            capital_exposure=Sum('capital_exposure'),
        )
        projection_totals = projections.aggregate(
            expected_recovery_value=Sum('expected_recovery_value'),
        )
        needs_review = queryset.filter(
            status__in={'GENERATED', 'RECOMMENDED', 'NEEDS_REVIEW', 'REVIEWED'},
            risk_class__in=self.HIGH_RISK_CLASSES,
        ).count()
        return Response({
            'total_decisions': queryset.count(),
            'at_risk_skus': high_risk.count(),
            'high_priority_count': queryset.filter(priority_tier__in={'P1', 'P2'}).count(),
            'needs_review_count': needs_review,
            'capital_exposure': float(totals['capital_exposure'] or 0),
            # This is a scenario total, not a booked financial outcome.  Only
            # price actions with an actual computed projection contribute.
            'projected_recovery_value': float(projection_totals['expected_recovery_value'] or 0),
            'projected_sku_count': projections.count(),
            'unprojected_at_risk_sku_count': max(0, high_risk.count() - projections.count()),
        }, status=status.HTTP_200_OK)


class DecisionDataStatusView(APIView):
    """Plain-language workspace data status for the merchant decision queue."""

    def get(self, request, *args, **kwargs):
        if not (
            getattr(request, 'tenant_context_validated', False)
            and getattr(request, 'workspace_id', None)
        ):
            return Response(
                {'success': False, 'error': {'code': 'UNAUTHENTICATED', 'message': 'Cần workspace đã xác thực để xem tình trạng dữ liệu.'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(DecisionTrustReportService.build(workspace_id=int(request.workspace_id)))


class DecisionLearningReportView(APIView):
    """A plain-language weekly report about merchant choices and data gaps."""

    def get(self, request, *args, **kwargs):
        if not (
            getattr(request, 'tenant_context_validated', False)
            and getattr(request, 'workspace_id', None)
        ):
            return Response(
                {'success': False, 'error': {'code': 'UNAUTHENTICATED', 'message': 'Cần workspace đã xác thực để xem báo cáo tuần.'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            days = int(request.query_params.get('days') or 7)
        except (TypeError, ValueError):
            return Response(
                {'success': False, 'error': {'code': 'INVALID_PERIOD', 'message': 'Số ngày phải là số nguyên hợp lệ.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(DecisionTrustReportService.learning_report(workspace_id=int(request.workspace_id), days=days))


class DecisionRevalidationView(APIView):
    """Show or explicitly renew the facts that make a decision safe to act on."""

    def _decision(self, request, decision_id):
        decision = DecisionPersistenceService.get_decision(decision_id)
        if not _decision_is_visible_to_request(request, decision):
            raise DecisionNotFoundError(f'Decision {decision_id} not found.')
        return decision

    def get(self, request, decision_id, *args, **kwargs):
        try:
            return Response(DecisionRevalidationService.passport(self._decision(request, decision_id)))
        except DecisionNotFoundError as exc:
            return Response(
                {'success': False, 'error': {'code': 'DECISION_NOT_FOUND', 'message': str(exc)}},
                status=status.HTTP_404_NOT_FOUND,
            )

    def post(self, request, decision_id, *args, **kwargs):
        try:
            decision = self._decision(request, decision_id)
            actor = str(
                request.data.get('actor')
                or getattr(request, 'user_email', None)
                or 'merchant'
            )[:128]
            passport = DecisionRevalidationService.approve(
                decision=decision,
                actor=actor,
                note=str(request.data.get('note') or '')[:2_000],
            )
            return Response({'success': True, **passport}, status=status.HTTP_201_CREATED)
        except DecisionNotFoundError as exc:
            return Response(
                {'success': False, 'error': {'code': 'DECISION_NOT_FOUND', 'message': str(exc)}},
                status=status.HTTP_404_NOT_FOUND,
            )
        except DecisionRevalidationError as exc:
            return Response(
                {'success': False, 'error': {'code': 'DECISION_REVALIDATION_REQUIRED', 'message': str(exc)}},
                status=status.HTTP_409_CONFLICT,
            )


class DecisionDetailView(APIView):
    """GET /api/v1/decisions/{decision_id}/: Retrieve a single decision context by decision_id."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            serializer = DecisionSerializer(decision)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )


class DecisionStatusUpdateView(APIView):
    """PATCH /api/v1/decisions/{decision_id}/status/: Update decision lifecycle status."""

    def patch(self, request, decision_id, *args, **kwargs):
        serializer = DecisionStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": {"code": "INVALID_STATUS", "message": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_status = serializer.validated_data["status"]
        actor = serializer.validated_data.get("actor", "merchant")
        notes = serializer.validated_data.get("notes", "")
        feedback_reason = serializer.validated_data.get('feedback_reason', '')
        feedback_note = serializer.validated_data.get('feedback_note', '')

        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            if new_status == 'EXECUTED':
                runtime = execution_runtime_status(decision)
                if runtime:
                    return Response(
                        {
                            'success': False,
                            'error': {
                                'code': 'MODEL_RUNTIME_NOT_READY',
                                'message': 'Không thể thực thi quyết định dựa trên mô hình khi model runtime chưa sẵn sàng.',
                            },
                            'model_runtime': runtime,
                        },
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
            decision = DecisionStatusService.update_status(
                decision_id=decision_id,
                new_status=new_status,
                actor=actor,
                notes=notes,
                metadata=(
                    {'merchant_feedback': {'reason': feedback_reason, 'note': feedback_note[:500]}}
                    if feedback_reason else None
                ),
            )
            response_serializer = DecisionSerializer(decision)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )
        except InvalidStatusTransitionError as e:
            return Response(
                {"success": False, "error": {"code": "INVALID_STATUS_TRANSITION", "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST
            )


class DecisionHistoryView(APIView):
    """GET /api/v1/decisions/{decision_id}/history/: Retrieve decision audit timeline history."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            history_data = DecisionHistoryService.get_history(decision_id)
            return Response(history_data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )


class DecisionExplanationView(APIView):
    """GET /api/v1/decisions/{decision_id}/explanation/: Retrieve M6-09 explanation payload."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            exp = decision.explanations.first()
            if not exp:
                return Response(
                    {"success": False, "error": {"code": "EXPLANATION_NOT_FOUND", "message": f"Explanation not found for decision {decision_id}."}},
                    status=status.HTTP_404_NOT_FOUND
                )
            serializer = DecisionExplanationSerializer(exp)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )


class DecisionSimulationView(APIView):
    """
    POST /api/v1/decisions/simulate/: SIM-001 & SIM-002 Simulation Engine Endpoint.
    
    Merchant Inputs:
    - discount_rate (default 0.15)
    - duration_days (default 14)
    - discount_rates (default [0.10, 0.15, 0.20])
    - decision_context or decision_id
    """

    PRICE_ACTIONS = {'DISCOUNT', 'CLEARANCE', 'PROMOTION'}
    # Decisions created before the governed recommendation contract used these
    # labels. Keep them executable without exposing storage-era labels to users.
    PRICE_ACTION_ALIASES = {
        'DISCOUNT_CLEARANCE': 'CLEARANCE',
        'FLASH_SALE': 'PROMOTION',
    }

    @classmethod
    def _normalise_price_action(cls, action_type):
        action = str(action_type or '').strip().upper().replace(' ', '_')
        return cls.PRICE_ACTION_ALIASES.get(action, action)

    @staticmethod
    def _observed_demand_state(*velocities):
        """Match the simulation engine's newest-observation demand policy."""
        for velocity in velocities:
            try:
                numeric_velocity = float(velocity)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric_velocity) and numeric_velocity >= 0:
                # A recent recorded zero must not be overridden by older demand.
                return True, numeric_velocity > 0
        return False, False

    def post(self, request, *args, **kwargs):
        from src.analytics.discount_simulation_engine import (
            DiscountSimulationEngine,
            DiscountSimulationError,
        )

        payload = request.data or {}
        try:
            discount_rate = float(payload.get("discount_rate", 0.15))
            duration_days = int(payload.get("duration_days", 14))
            custom_rates = [float(rate) for rate in payload.get("discount_rates", [0.10, 0.15, 0.20])]
        except (TypeError, ValueError):
            return Response({
                "success": False, "code": "INVALID_SIMULATION_INPUT",
                "detail": "Mức giảm giá và thời gian phải là số hợp lệ.",
            }, status=status.HTTP_400_BAD_REQUEST)
        if (
            not math.isfinite(discount_rate)
            or not 0 <= discount_rate <= 0.50
            or not 1 <= duration_days <= 90
            or not custom_rates
            or len(custom_rates) > 6
            or any(not math.isfinite(rate) or not 0 <= rate <= 0.50 for rate in custom_rates)
        ):
            return Response({
                "success": False, "code": "SIMULATION_GUARDRAIL_VIOLATION",
                "detail": "Mức giảm giá phải từ 0% đến 50%, thời gian từ 1 đến 90 ngày và tối đa 6 kịch bản.",
            }, status=status.HTTP_400_BAD_REQUEST)

        decision_ctx = payload.get("decision_context") or {}
        decision_id = payload.get("decision_id")

        if not decision_ctx and decision_id:
            try:
                decision_rec = DecisionPersistenceService.get_decision(decision_id)
                if not _decision_is_visible_to_request(request, decision_rec):
                    raise DecisionNotFoundError(f"Decision {decision_id} not found.")
                if self._normalise_price_action(decision_rec.action_type) not in self.PRICE_ACTIONS:
                    return Response({
                        "success": False,
                        "code": "SIMULATION_NOT_APPLICABLE",
                        "detail": "Kịch bản điều chỉnh giá chỉ áp dụng cho phương án liên quan đến giá.",
                    }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                inventory_query = InventoryRecord.objects.filter(
                    canonical_sku=decision_rec.sku,
                    as_of_verified=True,
                ).select_related('sku')
                if getattr(request, "tenant_context_validated", False):
                    inventory_query = inventory_query.filter(sku__workspace_id=request.workspace_id)
                inventory = inventory_query.order_by('-record_date', '-source_observed_at', '-id').first()
                if not inventory or inventory.selling_price is None or inventory.cost_price is None or inventory.available_quantity is None:
                    return Response({
                        "success": False,
                        "code": "SIMULATION_INPUT_UNAVAILABLE",
                        "detail": "SKU chưa có đủ giá bán, giá vốn và tồn kho đã xác thực để mô phỏng.",
                    }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                assessment_query = SlowMovingRiskAssessment.objects.filter(sku=decision_rec.sku)
                if getattr(request, "tenant_context_validated", False):
                    assessment_query = assessment_query.filter(session__workspace_id=request.workspace_id)
                assessment = assessment_query.order_by('-assessment_timestamp', '-created_at').first()
                evidence = assessment.evidence if assessment and isinstance(assessment.evidence, dict) else {}
                velocity_30d = evidence.get('sales_velocity_30d')
                velocity_90d = evidence.get('sales_velocity_90d')
                demand_observed, demand_positive = self._observed_demand_state(
                    velocity_30d,
                    velocity_90d,
                    evidence.get('sales_velocity_7d'),
                )
                if not demand_observed:
                    return Response({
                        "success": False,
                        "code": "SIMULATION_DEMAND_UNAVAILABLE",
                        "detail": "SKU có giá bán, giá vốn và tồn kho, nhưng chưa có dữ liệu nhu cầu bán được quan sát trong kỳ gần nhất. Không tạo dự báo doanh số từ giả định tồn kho.",
                    }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                if not demand_positive:
                    return Response({
                        "success": False,
                        "code": "SIMULATION_DEMAND_UNAVAILABLE",
                        "detail": "SKU có giá bán, giá vốn và tồn kho đầy đủ, nhưng chưa ghi nhận nhu cầu bán trong kỳ quan sát. Không tạo dự báo doanh số từ giảm giá.",
                    }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                decision_ctx = {
                    "sku": decision_rec.sku,
                    "unit_price": float(inventory.selling_price),
                    "unit_cost": float(inventory.cost_price),
                    "stock_on_hand": float(inventory.available_quantity),
                    "demand_context": {
                        "sales_velocity_30d": velocity_30d,
                        "sales_velocity_90d": velocity_90d,
                        "sales_velocity_7d": evidence.get('sales_velocity_7d'),
                        "observed": True,
                    },
                    "capital_context": {
                        "capital_exposure": float(decision_rec.capital_exposure)
                    }
                }
            except DecisionNotFoundError:
                return Response({
                    "success": False,
                    "code": "DECISION_NOT_FOUND",
                    "detail": "Không tìm thấy đề xuất thuộc bộ dữ liệu hiện tại.",
                }, status=status.HTTP_404_NOT_FOUND)

        if not decision_ctx:
            return Response({
                "success": False,
                "code": "SIMULATION_INPUT_REQUIRED",
                "detail": "Cần chọn một đề xuất có dữ liệu SKU để chạy mô phỏng.",
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            sim_engine = DiscountSimulationEngine()
            sim_001 = sim_engine.simulate_single_scenario(
                decision_context=decision_ctx,
                discount_rate=discount_rate,
                duration_days=duration_days
            )
            sim_002 = sim_engine.compare_scenarios(
                decision_context=decision_ctx,
                discount_rates=custom_rates,
                duration_days=duration_days
            )
        except (TypeError, ValueError, DiscountSimulationError) as exc:
            return Response({
                "success": False, "code": "SIMULATION_INPUT_UNAVAILABLE", "detail": str(exc),
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response({
            "success": True,
            "sku": decision_ctx.get("sku"),
            "sim_001": sim_001,
            "sim_002": sim_002
        }, status=status.HTTP_200_OK)
