import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'notesmanager.settings')

app = Celery('shizuha_notes')
app.config_from_object('django.conf:settings', namespace='CELERY')

# Configure task routing and naming to avoid conflicts
app.conf.update(
    task_default_queue='shizuha_notes',
    task_default_exchange='shizuha_notes',
    task_default_routing_key='shizuha_notes',
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

app.autodiscover_tasks()

# Configure Celery to handle connection errors gracefully
app.conf.broker_transport_options = {
    'retry_on_startup': True,
    'max_retries': 10,
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
