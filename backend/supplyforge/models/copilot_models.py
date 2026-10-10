"""
Django Database Models for Task M7-10 Copilot API & Persistence.
Module 07: AI Copilot & Merchant Workspace

Stores conversations, message histories, responses, tool calls, memories, and audit logs.
"""

from django.db import models
import uuid


class CopilotConversation(models.Model):
    conversation_id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
    tenant_id = models.CharField(max_length=64, db_index=True)
    merchant_id = models.CharField(max_length=64, db_index=True)
    user_id = models.CharField(max_length=64, default="user_default")
    title = models.CharField(max_length=255, default="New Copilot Session")
    status = models.CharField(max_length=32, default="ACTIVE")
    current_topic = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "copilot_conversations"


class CopilotMessage(models.Model):
    message_id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
    conversation = models.ForeignKey(CopilotConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=[("user", "User"), ("assistant", "Assistant"), ("system", "System")])
    content = models.TextField()
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "copilot_messages"


class CopilotToolCall(models.Model):
    tool_call_id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
    conversation = models.ForeignKey(CopilotConversation, on_delete=models.CASCADE, related_name="tool_calls")
    tool_name = models.CharField(max_length=64)
    source_module = models.CharField(max_length=32)
    input_params = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="SUCCESS")
    execution_time_ms = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "copilot_tool_calls"


class CopilotAuditLog(models.Model):
    request_id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
    conversation_id = models.CharField(max_length=64, db_index=True)
    tenant_id = models.CharField(max_length=64, db_index=True)
    merchant_id = models.CharField(max_length=64, db_index=True)
    intent_code = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default="SUCCESS")
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.FloatField(default=0.0)
    latency_ms = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "copilot_audit_logs"
