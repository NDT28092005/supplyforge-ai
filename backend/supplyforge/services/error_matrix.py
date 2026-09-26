import logging

logger = logging.getLogger(__name__)


class ErrorMatrixRegistry:
    """
    Error Matrix Registry — Requirement #22 Standardized Ingestion Errors.
    Defines standardized error codes, human descriptions, and system behaviors.
    """

    ERROR_MATRIX = {
        'ERR_FILE_FORMAT': {
            'code': 'ERR_FILE_FORMAT',
            'name': 'Invalid CSV',
            'system_behavior': 'Reject',
            'description': 'File CSV không hợp lệ hoặc sai định dạng bóc tách dòng/cột.',
            'http_status': 400
        },
        'ERR_SCHEMA_MISSING': {
            'code': 'ERR_SCHEMA_MISSING',
            'name': 'Missing column',
            'system_behavior': 'Reject',
            'description': 'Thiếu cột bắt buộc theo Schema Canonical (SKU, Date, Quantity).',
            'http_status': 400
        },
        'ERR_DATA_TYPE': {
            'code': 'ERR_DATA_TYPE',
            'name': 'Wrong datatype',
            'system_behavior': 'Reject / Row Reject',
            'description': 'Sai kiểu dữ liệu (ví dụ: ngày sai định dạng, số lượng không phải số nguyên).',
            'http_status': 422
        },
        'ERR_DUPLICATE': {
            'code': 'ERR_DUPLICATE',
            'name': 'Duplicate',
            'system_behavior': 'Skip / Report',
            'description': 'Bản ghi bị trùng lặp chính xác (bỏ qua và báo cáo trong log).',
            'http_status': 200
        },
        'ERR_EMPTY_FILE': {
            'code': 'ERR_EMPTY_FILE',
            'name': 'Empty file',
            'system_behavior': 'Reject',
            'description': 'Tệp dữ liệu rỗng (0 dòng hoặc chỉ chứa khoảng trắng).',
            'http_status': 400
        },
        'ERR_FILE_SIZE': {
            'code': 'ERR_FILE_SIZE',
            'name': 'File too large',
            'system_behavior': 'Reject',
            'description': 'Dung lượng tệp vượt quá giới hạn hệ thống (> 500 MB).',
            'http_status': 400
        },
        'ERR_ENCODING': {
            'code': 'ERR_ENCODING',
            'name': 'Unsupported encoding',
            'system_behavior': 'Reject',
            'description': 'Mã hóa tệp không được hỗ trợ (chỉ hỗ trợ UTF-8 / UTF-8 BOM / ASCII).',
            'http_status': 400
        },
        'ERR_PROCESSING_TIMEOUT': {
            'code': 'ERR_PROCESSING_TIMEOUT',
            'name': 'Processing timeout',
            'system_behavior': 'Retry',
            'description': 'Tiến trình xử lý bị quá thời gian cho phép (timeout worker).',
            'http_status': 504
        },
        'ERR_DATABASE': {
            'code': 'ERR_DATABASE',
            'name': 'Database error',
            'system_behavior': 'Rollback',
            'description': 'Lỗi cơ sở dữ liệu khi lưu bản ghi (tự động rollback transaction).',
            'http_status': 500
        },
        'ERR_WORKER': {
            'code': 'ERR_WORKER',
            'name': 'Worker failure',
            'system_behavior': 'Retry',
            'description': 'Lỗi tiến trình Celery / Worker ngầm (tự động thử lại).',
            'http_status': 500
        },
        'ERR_AUTH': {
            'code': 'ERR_AUTH',
            'name': 'Unauthorized',
            'system_behavior': 'Reject',
            'description': 'Không có quyền truy cập hoặc phiên đăng nhập hết hạn.',
            'http_status': 401
        },
        'ERR_IMPORT_CONFLICT': {
            'code': 'ERR_IMPORT_CONFLICT',
            'name': 'Concurrent import',
            'system_behavior': 'Queue / Reject',
            'description': 'Xung đột tiến trình nạp tệp đồng thời trên cùng workspace.',
            'http_status': 409
        },
    }

    @classmethod
    def get_error_detail(cls, error_code: str) -> dict:
        """Return standardized error definition by code."""
        return cls.ERROR_MATRIX.get(
            error_code,
            {
                'code': error_code,
                'name': 'Unknown Error',
                'system_behavior': 'Reject',
                'description': 'Lỗi không xác định.',
                'http_status': 500
            }
        )

    @classmethod
    def list_matrix(cls) -> list:
        """Return full list of registered error codes and behaviors."""
        return list(cls.ERROR_MATRIX.values())
