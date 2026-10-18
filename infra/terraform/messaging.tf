locals {
  dlq_names = {
    ingestion = "sf-dev-ingestion-dlq"
    transform = "sf-dev-transform-dlq"
    analytics = "sf--dev-analytics-dlq"
    ml        = "sf-dev-ml-dlq"
  }

  work_queue_names = {
    ingestion_events = "sf-dev-ingestion-events"
    transform        = "sf-dev-transform"
    analytics        = "sf-dev-analytics"
    ml               = "sf-dev-ml"
  }

  work_queue_dlq = {
    ingestion_events = "ingestion"
    transform        = "transform"
    analytics        = "analytics"
    ml               = "ml"
  }
}

resource "aws_sqs_queue" "dlq" {
  for_each = local.dlq_names

  name                      = each.value
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "work" {
  for_each = local.work_queue_names

  name                       = each.value
  visibility_timeout_seconds = 900
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[local.work_queue_dlq[each.key]].arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "ingestion_events" {
  statement {
    sid    = "AllowEventBridgeToSendIngestionEvents"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.work["ingestion_events"].arn]
  }
}

resource "aws_sqs_queue_policy" "ingestion_events" {
  queue_url = aws_sqs_queue.work["ingestion_events"].id
  policy    = data.aws_iam_policy_document.ingestion_events.json
}

resource "aws_cloudwatch_event_rule" "raw_object_created" {
  name        = "sf-dev-raw-upload"
  description = "Queue raw SupplyForge uploads for idempotent ingestion"
  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = {
        name = [aws_s3_bucket.data["raw"].bucket]
      }
      object = {
        key = [{
          prefix = "raw/"
        }]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "raw_object_created" {
  rule      = aws_cloudwatch_event_rule.raw_object_created.name
  target_id = var.eventbridge_target_id
  arn       = aws_sqs_queue.work["ingestion_events"].arn
  role_arn  = aws_iam_role.eventbridge_sqs.arn
}
