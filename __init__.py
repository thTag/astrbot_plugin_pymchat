"""PymChat Plugin for AstrBot.

This plugin provides:
1. LLM tools for interacting with PymChat chatroom
2. Platform adapter for polling notifications
"""

from .main import PymChatPlugin

__all__ = ["PymChatPlugin"]