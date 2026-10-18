"""Consume the EventBridge-to-SQS ingestion queue without duplicate jobs."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from supplyforge.services.s3_multipart_ingestion import S3MultipartIngestionService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Consume S3 Object Created events from the SupplyForge ingestion SQS queue.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Poll once then exit.')
        parser.add_argument('--max-messages', type=int, default=10)

    def handle(self, *args, **options):
        queue_url = settings.SQS_INGESTION_QUEUE_URL
        if not queue_url:
            raise CommandError('SQS_INGESTION_QUEUE_URL is required.')
        if not 1 <= options['max_messages'] <= 10:
            raise CommandError('--max-messages must be between 1 and 10.')

        import boto3

        client = boto3.client('sqs', region_name=settings.S3_REGION or None)
        while True:
            response = client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=options['max_messages'],
                WaitTimeSeconds=20,
                VisibilityTimeout=300,
            )
            messages = response.get('Messages', [])
            for message in messages:
                try:
                    event = json.loads(message['Body'])
                    payload, created = S3MultipartIngestionService.handle_object_created_event(event)
                    logger.info('Processed S3 ingestion event: payload=%s created=%s', payload, created)
                except Exception:
                    logger.exception('S3 ingestion event failed; leaving message for retry/DLQ.')
                    continue
                client.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=message['ReceiptHandle'],
                )
            if options['once']:
                return
