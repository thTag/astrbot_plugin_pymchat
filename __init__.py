# 修改后的 __init__.py
"""PymChat Plugin for AstrBot.
This plugin provides:
1. LLM tools for interacting with PymChat chatroom
2. Platform adapter for polling notifications
3. Cross-session memory for chat activities
"""
from .main import PymChatPlugin
__all__ = ["PymChatPlugin"]