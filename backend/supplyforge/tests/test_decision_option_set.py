from django.test import SimpleTestCase

from supplyforge.services.decision_option_set import DecisionOptionSetService


class DecisionOptionSetServiceTests(SimpleTestCase):
    def test_persists_three_clear_options_without_internal_scores(self):
        option_set = DecisionOptionSetService.build(
            recommendation={
                'action': {
                    'type': 'DISCOUNT',
                    'parameters': {'approval_required': False},
                },
            },
            eligibility={
                'action_evaluations': [
                    {'action_id': 'HOLD', 'status': 'INELIGIBLE', 'reasons': [
                        {'rule': 'HOLD_INELIGIBLE', 'message': 'Chỉ giữ giá khi rủi ro ở mức thấp.'},
                    ]},
                    {'action_id': 'DISCOUNT', 'status': 'ELIGIBLE', 'reasons': [
                        {'rule': 'HIGH_RISK_DISCOUNT', 'message': 'Đủ điều kiện điều chỉnh giá có kiểm soát.'},
                    ]},
                    {'action_id': 'CLEARANCE', 'status': 'REQUIRES_REVIEW', 'reasons': [
                        {'rule': 'REQUIRES_EXECUTIVE_REVIEW', 'message': 'Cần phê duyệt trước khi xả hàng nhanh.'},
                    ]},
                ],
            },
            commercial_facts={
                'state': 'READY', 'source_type': 'CSV', 'source_key': 'CSV',
                'analysis_as_of': '2026-10-29T23:59:59+00:00',
                'source_scope': {'warehouse_scope': 'ALL_VERIFIED_WAREHOUSES'},
            },
            projection_usable=True,
            value={
                'evaluation_status': 'READY',
                'projected_gross_sales': 12_000_000,
                'projected_net_contribution': 2_100_000,
                'projected_inventory_cost_rotation': 7_000_000,
            },
            optimization={
                'evaluation_status': 'READY',
                'projected_inventory_cost_rotation': 7_100_000,
            },
        )

        options = option_set['options']
        self.assertEqual(options[0]['label'], 'Giảm giá có kiểm soát')
        self.assertEqual(options[0]['status'], 'READY')
        self.assertEqual(
            options[0]['financial_scenario']['projected_inventory_cost_rotation'], 7_100_000.0,
        )
        self.assertEqual(options[1]['label'], 'Giữ giá và theo dõi')
        self.assertEqual(options[2]['label'], 'Xả hàng nhanh có phê duyệt')
        self.assertEqual(options[2]['status'], 'APPROVAL_REQUIRED')
        self.assertTrue(all('score' not in option and 'action' not in option for option in options))

    def test_missing_price_evidence_withholds_option_financials(self):
        option_set = DecisionOptionSetService.build(
            recommendation={'action': {'type': 'DISCOUNT', 'parameters': {}}},
            eligibility={
                'action_evaluations': [
                    {'action_id': 'DISCOUNT', 'status': 'INELIGIBLE', 'reasons': [
                        {
                            'rule': 'DISCOUNT_REQUIRES_POSITIVE_DEMAND',
                            'message': 'Cần nhu cầu bán quan sát được trước khi điều chỉnh giá.',
                        },
                    ]},
                ],
            },
            commercial_facts={'state': 'DATA_NEEDED'},
            projection_usable=False,
            value=None,
            optimization=None,
        )

        discount = next(option for option in option_set['options'] if option['option_key'] == 'CONTROLLED_DISCOUNT')
        self.assertEqual(discount['status'], 'DATA_NEEDED')
        self.assertEqual(discount['financial_scenario']['status'], 'DATA_NEEDED')
        self.assertNotIn('projected_inventory_cost_rotation', discount['financial_scenario'])
