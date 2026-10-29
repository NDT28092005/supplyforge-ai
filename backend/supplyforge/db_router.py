"""Optional read-replica routing.

The router is inert until a ``replica`` database is configured. Writes and
transactions stay on ``default`` so read-after-write behavior remains
consistent for normal request flows.
"""

from django.conf import settings


class ReadReplicaRouter:
    def db_for_read(self, model, **hints):
        # An import is a multi-request workflow: upload writes an
        # IngestionSession and mapping/profiling reads it immediately after.
        # Reading these operational records from an asynchronous replica can
        # falsely report a newly created session as missing.
        primary_read_models = {
            'ingestionsession',
            'datasetversion',
            'backgroundjob',
            'slowmovingriskassessment',
            'riskmonitoringrun',
            'riskexplanationrecord',
        }
        if model._meta.app_label == 'supplyforge' and model._meta.model_name in primary_read_models:
            return 'default'
        if 'replica' in settings.DATABASES and not hints.get('instance'):
            return 'replica'
        return None

    def db_for_write(self, model, **hints):
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        databases = {'default', 'replica'}
        if obj1._state.db in databases and obj2._state.db in databases:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == 'replica':
            return False
        return None
