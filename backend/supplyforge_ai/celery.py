import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'supplyforge_ai.settings')

app = Celery('supplyforge_ai')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
