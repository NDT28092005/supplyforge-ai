"""Merchant-safe, persisted decision options.

Strategy suitability is an internal diagnostic used to select one candidate.
It is not a return-on-investment score and must not be shown as such to a
merchant.  This module turns the immutable eligibility result for a decision
into a small, localised display contract with explicit readiness and evidence
gaps.  It deliberately does not manufacture a financial estimate for options
that have not been simulated from the decision-time facts.
"""

from __future__ import annotations

from typing import Any


class DecisionOptionSetService:
    """Build an immutable merchant-facing option set for one decision."""

    VERSION = "MERCHANT_DECISION_OPTIONS_V1"

    # The three options a merchant most commonly needs to compare are always
    # present.  Other operational routes are appended only when the policy
    # evaluated them, except for a supplier return which must stay a manual
    # route until supplier terms/evidence have been supplied.
    CORE_ACTIONS = ("HOLD", "DISCOUNT", "CLEARANCE")
    DISPLAY = {
        "HOLD": {
            "key": "KEEP_PRICE",
            "label": "Giữ giá và theo dõi",
            "tradeoff": "Không làm giảm biên ngay, nhưng tồn có thể tiếp tục quay vòng chậm.",
        },
        "DISCOUNT": {
            "key": "CONTROLLED_DISCOUNT",
            "label": "Giảm giá có kiểm soát",
            "tradeoff": "Có thể hỗ trợ tốc độ bán; chỉ áp dụng sau khi kiểm tra giá sàn và biên lợi nhuận.",
        },
        "CLEARANCE": {
            "key": "FAST_CLEARANCE",
            "label": "Xả hàng nhanh có phê duyệt",
            "tradeoff": "Ưu tiên giảm lượng tồn; cần chấp nhận và kiểm soát mức giá, phạm vi áp dụng.",
        },
        "PROMOTION": {
            "key": "CAMPAIGN_PROMOTION",
            "label": "Khuyến mại có kiểm soát",
            "tradeoff": "Tạo lực đẩy theo chiến dịch; cần đối chiếu chi phí ưu đãi và phạm vi kênh.",
        },
        "BUNDLE": {
            "key": "BUNDLE_OFFER",
            "label": "Bán theo gói",
            "tradeoff": "Bảo vệ giá niêm yết tốt hơn; cần xác nhận sản phẩm ghép phù hợp.",
        },
        "REPOSITION": {
            "key": "REPOSITION_STOCK",
            "label": "Điều chuyển hoặc đổi kênh",
            "tradeoff": "Có thể phù hợp với nhu cầu ở nơi khác; cần xác nhận tồn và năng lực thực hiện theo phạm vi mới.",
        },
        "STOP_REPLENISHMENT": {
            "key": "PAUSE_REPLENISHMENT",
            "label": "Tạm dừng tái nhập",
            "tradeoff": "Ngăn chôn thêm giá vốn; không làm giảm lượng tồn hiện có ngay.",
        },
        "RETURN_TO_SUPPLIER": {
            "key": "RETURN_TO_SUPPLIER",
            "label": "Hoàn trả nhà cung cấp",
            "tradeoff": "Có thể giảm tồn mà không giảm giá; cần điều khoản nhận lại hàng và chứng từ đối soát.",
        },
        "MONITOR": {
            "key": "MONITOR",
            "label": "Theo dõi thêm",
            "tradeoff": "Ít thay đổi vận hành; chỉ phù hợp khi tín hiệu rủi ro chưa đủ mạnh để can thiệp.",
        },
    }
    PRICE_ACTIONS = {"DISCOUNT", "CLEARANCE", "PROMOTION"}

    @classmethod
    def build(
        cls,
        *,
        recommendation: dict[str, Any],
        eligibility: dict[str, Any],
        commercial_facts: dict[str, Any],
        projection_usable: bool,
        value: dict[str, Any] | None,
        optimization: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return a JSON-safe snapshot fit for ``DecisionRecord.action_parameters``."""
        parameters = (recommendation.get("action") or {}).get("parameters") or {}
        recommended_action = cls._normalise((recommendation.get("action") or {}).get("type"))
        evaluation_by_action = {
            cls._normalise(row.get("action_id")): row
            for row in (eligibility.get("action_evaluations") or [])
            if isinstance(row, dict) and cls._normalise(row.get("action_id"))
        }
        actions = list(cls.CORE_ACTIONS)
        for action in evaluation_by_action:
            if action in cls.DISPLAY and action not in actions:
                actions.append(action)
        if "RETURN_TO_SUPPLIER" not in actions:
            actions.append("RETURN_TO_SUPPLIER")

        options = [
            cls._option(
                action=action,
                recommended_action=recommended_action,
                evaluation=evaluation_by_action.get(action),
                approval_required=bool(parameters.get("approval_required")),
                projection_usable=projection_usable,
                value=value,
                optimization=optimization,
            )
            for action in actions
        ]
        # The recommended route is presented first, while the core three are
        # still preserved for an honest comparison.  No strategy score leaves
        # this service.
        options.sort(key=lambda option: (not option["is_recommended"], actions.index(option["_action"])))
        for option in options:
            option.pop("_action", None)

        source_scope = commercial_facts.get("source_scope") if isinstance(commercial_facts, dict) else {}
        if not isinstance(source_scope, dict):
            source_scope = {}
        return {
            "version": cls.VERSION,
            "scope": {
                "source_type": commercial_facts.get("source_type") if isinstance(commercial_facts, dict) else None,
                "source_key": commercial_facts.get("source_key") if isinstance(commercial_facts, dict) else None,
                "analysis_as_of": commercial_facts.get("analysis_as_of") if isinstance(commercial_facts, dict) else None,
                "warehouse_scope": source_scope.get("warehouse_scope") or source_scope.get("warehouse_ids"),
                "channel_scope": source_scope.get("channel") or source_scope.get("order_platforms"),
                "fact_state": commercial_facts.get("state") if isinstance(commercial_facts, dict) else "DATA_NEEDED",
            },
            "options": options,
            "financial_boundary": (
                "Chỉ phương án đã có kịch bản từ giá, giá vốn, tồn kho và nhu cầu quan sát mới hiển thị số tài chính. "
                "Các số đó là kịch bản, không phải doanh thu hay tiền thực nhận."
            ),
        }

    @classmethod
    def _option(
        cls,
        *,
        action: str,
        recommended_action: str,
        evaluation: dict[str, Any] | None,
        approval_required: bool,
        projection_usable: bool,
        value: dict[str, Any] | None,
        optimization: dict[str, Any] | None,
    ) -> dict[str, Any]:
        display = cls.DISPLAY[action]
        is_recommended = action == recommended_action
        if action == "RETURN_TO_SUPPLIER" and evaluation is None:
            status, status_label = "DATA_NEEDED", "Cần xác nhận điều khoản"
            reasons = ["Cần điều khoản nhận lại hàng, người phụ trách và chứng từ trước khi lập kế hoạch."]
        else:
            raw_status = str((evaluation or {}).get("status") or "INELIGIBLE").upper()
            reasons = cls._public_reasons((evaluation or {}).get("reasons"))
            status, status_label = cls._merchant_status(
                raw_status=raw_status,
                reasons=(evaluation or {}).get("reasons"),
                is_recommended=is_recommended,
                approval_required=approval_required,
            )

        option = {
            "option_key": display["key"],
            # Kept temporarily while sorting, then removed before persistence.
            "_action": action,
            "label": display["label"],
            "tradeoff": display["tradeoff"],
            "status": status,
            "status_label": status_label,
            "is_recommended": is_recommended,
            "reasons": reasons,
            "financial_scenario": cls._financial_scenario(
                action=action,
                is_recommended=is_recommended,
                projection_usable=projection_usable,
                value=value,
                optimization=optimization,
            ),
        }
        return option

    @classmethod
    def _merchant_status(
        cls,
        *,
        raw_status: str,
        reasons: Any,
        is_recommended: bool,
        approval_required: bool,
    ) -> tuple[str, str]:
        rules = {
            str(reason.get("rule") or "").upper()
            for reason in (reasons or []) if isinstance(reason, dict)
        }
        data_rules = {
            rule for rule in rules
            if any(token in rule for token in ("DEMAND", "CONFIDENCE", "INSUFFICIENT", "NOT_READY", "PO_REVIEW", "BUNDLE_PARTNER"))
        }
        if raw_status == "BLOCKED":
            return ("DATA_NEEDED", "Cần bổ sung dữ liệu") if data_rules else ("BLOCKED", "Đang bị chặn")
        if raw_status == "REQUIRES_REVIEW":
            if data_rules:
                return "DATA_NEEDED", "Cần bổ sung dữ liệu"
            return "APPROVAL_REQUIRED", "Cần phê duyệt"
        if raw_status == "ELIGIBLE":
            if is_recommended and approval_required:
                return "APPROVAL_REQUIRED", "Cần phê duyệt"
            return ("READY", "Sẵn sàng lập kế hoạch") if is_recommended else ("AVAILABLE", "Có thể cân nhắc")
        if data_rules:
            return "DATA_NEEDED", "Cần bổ sung dữ liệu"
        return "NOT_RECOMMENDED", "Chưa phù hợp lúc này"

    @classmethod
    def _financial_scenario(
        cls,
        *,
        action: str,
        is_recommended: bool,
        projection_usable: bool,
        value: dict[str, Any] | None,
        optimization: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if action not in cls.PRICE_ACTIONS:
            return {
                "status": "NOT_APPLICABLE",
                "message": "Phương án này không dùng kịch bản điều chỉnh giá.",
            }
        if not is_recommended:
            return {
                "status": "NOT_CALCULATED_FOR_OPTION",
                "message": "Chưa lập kịch bản riêng cho phương án này; hệ thống không so sánh số tài chính bằng giả định chung.",
            }
        if not projection_usable or not isinstance(value, dict) or value.get("evaluation_status") == "DATA_UNAVAILABLE":
            return {
                "status": "DATA_NEEDED",
                "message": "Cần đủ giá bán, giá vốn, tồn kho và nhu cầu quan sát trong cùng phạm vi trước khi lập kịch bản.",
            }
        source = optimization if isinstance(optimization, dict) and optimization.get("evaluation_status") == "READY" else value
        return {
            "status": "SCENARIO_ESTIMATE",
            "projected_inventory_cost_rotation": cls._number(source.get("projected_inventory_cost_rotation")),
            "projected_net_contribution": cls._number(value.get("projected_net_contribution")),
            "projected_gross_sales": cls._number(value.get("projected_gross_sales")),
            "message": "Kịch bản từ dữ liệu quan sát tại thời điểm quyết định; không phải doanh thu hoặc tiền thực nhận.",
        }

    @staticmethod
    def _public_reasons(raw_reasons: Any) -> list[str]:
        messages: list[str] = []
        for reason in raw_reasons or []:
            if not isinstance(reason, dict):
                continue
            message = str(reason.get("message") or "").strip()
            if message and message not in messages:
                messages.append(message)
        return messages

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return round(float(value), 2) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalise(value: Any) -> str:
        aliases = {"DISCOUNT_CLEARANCE": "CLEARANCE", "FLASH_SALE": "PROMOTION"}
        normalized = str(value or "").strip().upper().replace(" ", "_")
        return aliases.get(normalized, normalized)
