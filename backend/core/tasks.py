import time
from celery import shared_task
from .services import DynamicFileImportService

@shared_task(bind=True)
def process_file_import_async(self, file_path, mapping_rule, user_id):
    """
    Background Celery worker task to process large Excel/CSV imports asynchronously.
    Updates task state so frontend can poll progress.
    """
    self.update_state(state='PROCESSING', meta={'progress': 10, 'message': 'Starting file parse...'})
    
    try:
        # Simulate processing phases for progress reporting
        time.sleep(1)
        self.update_state(state='PROCESSING', meta={'progress': 40, 'message': 'Executing AI fuzzy matching & column normalization...'})
        
        # Read file from storage and execute import logic
        with open(file_path, 'rb') as f:
            result = DynamicFileImportService.process_batch_import(f, mapping_rule, user_id)
            
        self.update_state(state='PROCESSING', meta={'progress': 90, 'message': 'Saving products to database...'})
        time.sleep(0.5)
        
        return {
            'status': 'SUCCESS',
            'progress': 100,
            'message': 'Import completed successfully.',
            'result': result
        }
    except Exception as e:
        self.update_state(state='FAILURE', meta={'progress': 100, 'message': str(e)})
        raise e
