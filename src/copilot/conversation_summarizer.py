"""
Conversation Summarizer for Task M7-09 Conversation & Memory.
Module 07: AI Copilot & Merchant Workspace

Compresses long conversation message histories within token budgets.
"""

from typing import List, Dict, Any


class ConversationSummarizer:
    """Compresses message histories into compact conversation summaries."""

    @classmethod
    def summarize_messages(
        cls,
        messages: List[Dict[str, Any]],
        max_recent_turns: int = 4
    ) -> Dict[str, Any]:

        if len(messages) <= max_recent_turns * 2:
            return {
                "summary": "Hội thoại ngắn, chưa cần nén bối cảnh.",
                "recent_messages": messages
            }

        old_messages = messages[:-max_recent_turns * 2]
        recent_messages = messages[-max_recent_turns * 2:]

        summary_lines = []
        for msg in old_messages:
            if msg.get("role") == "user":
                summary_lines.append(f"- Người dùng đã hỏi: '{msg.get('content')}'")

        summary_text = f"Tóm tắt các lượt trao đổi trước:\n" + "\n".join(summary_lines[:5])

        return {
            "summary": summary_text,
            "recent_messages": recent_messages
        }
