"""
Canonical Schema Validation Engine — Module 01 Data Ingestion (TASK 04)
=========================================================================
Inspects dataset post-column mapping against System Canonical Schema rules.
Does NOT clean or modify raw data values.

Outputs standard report artifact to reports/schema_validation_report.json
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


class SchemaValidator:
    """Canonical Schema Validation Engine for Post-Mapping Datasets."""

    REQUIRED_CANONICAL_FIELDS = ['sku', 'date', 'quantity']
    OPTIONAL_CANONICAL_FIELDS = [
        'product_name', 'category', 'brand', 'price', 'cost',
        'order_id', 'promotion', 'discount', 'inventory'
    ]

    EXPECTED_TYPES = {
        'sku': 'String',
        'product_name': 'String',
        'date': 'Datetime',
        'quantity': 'Numeric',
        'price': 'Numeric',
        'cost': 'Numeric',
        'category': 'String',
        'brand': 'String',
        'order_id': 'String',
        'promotion': 'Numeric',
        'discount': 'Numeric',
        'inventory': 'Numeric',
    }

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def validate_schema(
        self,
        df: pd.DataFrame,
        mapping_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run full 8-step canonical schema validation suite."""
        schema_errors: List[str] = []
        schema_warnings: List[str] = []

        # Extract mapped dictionary: canonical_field -> list of source_columns
        canonical_to_sources: Dict[str, List[str]] = {}
        source_to_canonical: Dict[str, str] = {}

        mappings = mapping_result.get('mappings') or []
        for item in mappings:
            src = item.get('source_column')
            can = item.get('canonical_field')
            if src and can:
                source_to_canonical[src] = can
                if can not in canonical_to_sources:
                    canonical_to_sources[can] = []
                canonical_to_sources[can].append(src)

        # ── 1. Validate Required Fields ───────────────────────────────
        required_fields_status = {}
        for req_field in self.REQUIRED_CANONICAL_FIELDS:
            is_found = req_field in canonical_to_sources and len(canonical_to_sources[req_field]) > 0
            required_fields_status[req_field] = is_found
            if not is_found:
                schema_errors.append(f"Required canonical field \"{req_field}\" is missing.")

        # ── 2. Validate Column Uniqueness ─────────────────────────────
        for can_field, sources in canonical_to_sources.items():
            if len(sources) > 1:
                schema_errors.append(
                    f"Multiple source columns mapped to canonical field \"{can_field}\": {sources}"
                )

        # ── 3. Validate Data Types ────────────────────────────────────
        datatype_checks = {}
        for can_field, sources in canonical_to_sources.items():
            for src_col in sources:
                if src_col in df.columns:
                    series = df[src_col]
                    expected_type = self.EXPECTED_TYPES.get(can_field, 'String')
                    detected_type = str(series.dtype)

                    if expected_type == 'Numeric' and not pd.api.types.is_numeric_dtype(series):
                        schema_warnings.append(
                            f"Field \"{can_field}\" (column '{src_col}') expected Numeric datatype but detected '{detected_type}'."
                        )
                        datatype_checks[can_field] = {'expected': expected_type, 'detected': detected_type, 'status': 'WARNING'}
                    elif expected_type == 'Datetime' and not pd.api.types.is_datetime64_any_dtype(series):
                        # Try parsing sample
                        parsed = pd.to_datetime(series, errors='coerce')
                        if parsed.dropna().empty:
                            schema_warnings.append(
                                f"Field \"{can_field}\" (column '{src_col}') expected Datetime but values failed datetime parsing."
                            )
                            datatype_checks[can_field] = {'expected': expected_type, 'detected': detected_type, 'status': 'WARNING'}
                        else:
                            datatype_checks[can_field] = {'expected': expected_type, 'detected': detected_type, 'status': 'VALID'}
                    else:
                        datatype_checks[can_field] = {'expected': expected_type, 'detected': detected_type, 'status': 'VALID'}

        # ── 4. Validate Semantic Compatibility ────────────────────────
        semantic_checks = {}
        if 'quantity' in canonical_to_sources:
            qty_src = canonical_to_sources['quantity'][0]
            if qty_src in df.columns:
                samples = df[qty_src].dropna().astype(str).tolist()[:10]
                # Identifier check on quantity: e.g. long ID strings
                if samples and all(len(s) >= 9 and s.isdigit() for s in samples):
                    schema_warnings.append(
                        f"Column '{qty_src}' mapped to \"quantity\" appears to contain identifier-like values (e.g. {samples[0]}). Possible mapping error."
                    )
                    semantic_checks['quantity'] = 'WARNING_IDENTIFIER_LIKE'
                else:
                    semantic_checks['quantity'] = 'VALID'

        # ── 5. Validate Temporal Field ────────────────────────────────
        temporal_info = {}
        if 'date' in canonical_to_sources and canonical_to_sources['date'][0] in df.columns:
            date_src = canonical_to_sources['date'][0]
            parsed_dates = pd.to_datetime(df[date_src], errors='coerce').dropna()

            if not parsed_dates.empty:
                min_date = parsed_dates.min().strftime('%Y-%m-%d')
                max_date = parsed_dates.max().strftime('%Y-%m-%d')
                obs_days = max(1, (parsed_dates.max() - parsed_dates.min()).days + 1)

                temporal_info = {
                    'minDate': min_date,
                    'maxDate': max_date,
                    'observationPeriodDays': obs_days,
                    'parsedCount': len(parsed_dates),
                    'nullCount': int(df[date_src].isna().sum()),
                    'status': 'VALID' if obs_days >= 14 else 'WARNING',
                }

                if obs_days < 14:
                    schema_warnings.append(
                        f"Observation period ({obs_days} days) is insufficient for time-series slow-moving analysis."
                    )
            else:
                schema_warnings.append("Date field exists but all sample values failed datetime parsing.")
                temporal_info = {'status': 'INVALID'}

        # ── 6. Validate Quantity Field ────────────────────────────────
        quantity_info = {}
        if 'quantity' in canonical_to_sources and canonical_to_sources['quantity'][0] in df.columns:
            qty_src = canonical_to_sources['quantity'][0]
            qty_series = pd.to_numeric(df[qty_src], errors='coerce')

            null_count = int(qty_series.isna().sum())
            zero_count = int((qty_series == 0).sum())
            negative_count = int((qty_series < 0).sum())

            quantity_info = {
                'nullCount': null_count,
                'zeroSalesCount': zero_count,  # quantity = 0 is VALID DATA
                'negativeValueCount': negative_count,
                'zeroSalesIsValid': True,  # Explicit specification requirement
                'status': 'WARNING' if negative_count > 0 else 'VALID',
            }

            if negative_count > 0:
                schema_warnings.append(
                    f"Detected {negative_count} negative values in quantity field. Requires Data Cleaning."
                )

        # ── 7. Validate Business Field Availability Tiering ───────────
        optional_fields_status = {}
        for opt_field in self.OPTIONAL_CANONICAL_FIELDS:
            is_found = opt_field in canonical_to_sources and len(canonical_to_sources[opt_field]) > 0
            optional_fields_status[opt_field] = is_found
            if not is_found:
                schema_warnings.append(f"{opt_field} field is missing")

        total_records = len(df)
        data_tiers = {
            'coreData': {
                'sku': 'sku' in canonical_to_sources,
                'date': 'date' in canonical_to_sources,
                'quantity': 'quantity' in canonical_to_sources,
                'completenessPct': 100.0 if (required_fields_status.get('sku') and required_fields_status.get('date') and required_fields_status.get('quantity')) else 0.0,
            },
            'productMetadata': {
                'productName': 'product_name' in canonical_to_sources,
                'category': 'category' in canonical_to_sources,
                'brand': 'brand' in canonical_to_sources,
            },
            'financialData': {
                'price': 'price' in canonical_to_sources,
                'cost': 'cost' in canonical_to_sources,
            },
            'promotionData': {
                'promotion': 'promotion' in canonical_to_sources,
                'discount': 'discount' in canonical_to_sources,
            },
            'inventoryData': {
                'inventory': 'inventory' in canonical_to_sources,
            },
        }

        # ── 8. Scope Validation & Capabilities Matrix ────────────────
        capabilities = {
            'slowMovingProductRiskDetection': {
                'supported': required_fields_status.get('sku') and required_fields_status.get('date') and required_fields_status.get('quantity'),
                'requirements': 'Requires sku, date, quantity',
                'status': 'SUPPORTED' if (required_fields_status.get('sku') and required_fields_status.get('date') and required_fields_status.get('quantity')) else 'UNSUPPORTED',
            },
            'financialInventoryValuation': {
                'supported': 'cost' in canonical_to_sources,
                'requirements': 'Requires cost field',
                'status': 'SUPPORTED' if 'cost' in canonical_to_sources else 'REQUIRES_COST',
            },
            'promotionEffectAnalysis': {
                'supported': ('promotion' in canonical_to_sources or 'discount' in canonical_to_sources),
                'requirements': 'Requires promotion or discount field',
                'status': 'SUPPORTED' if ('promotion' in canonical_to_sources or 'discount' in canonical_to_sources) else 'REQUIRES_PROMOTION',
            },
            'physicalInventoryRiskDetection': {
                'supported': 'inventory' in canonical_to_sources,
                'requirements': 'Requires inventory snapshot field',
                'status': 'SUPPORTED' if 'inventory' in canonical_to_sources else 'REQUIRES_INVENTORY',
            },
        }

        # Overall Status Determination
        if schema_errors:
            overall_status = 'INVALID'
        elif schema_warnings:
            overall_status = 'VALID_WITH_WARNINGS'
        else:
            overall_status = 'VALID'

        report = {
            'sessionId': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'status': overall_status,
            'required_fields': required_fields_status,
            'optional_fields': optional_fields_status,
            'schema_errors': schema_errors,
            'schema_warnings': schema_warnings,
            'slow_moving_detection_ready': capabilities['slowMovingProductRiskDetection']['supported'],
            'datatypeChecks': datatype_checks,
            'semanticChecks': semantic_checks,
            'temporalValidation': temporal_info,
            'quantityValidation': quantity_info,
            'dataTiers': data_tiers,
            'capabilities': capabilities,
        }

        return report

    def export_report(self, report_result: Dict[str, Any], output_dir: str = 'reports/') -> str:
        """Export reports/schema_validation_report.json."""
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, 'schema_validation_report.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(report_result, f, indent=2, ensure_ascii=False)
        return file_path
