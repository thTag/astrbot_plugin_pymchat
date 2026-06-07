"""PymChat Message Event - Event class for chat interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain

if TYPE_CHECKING:
    from .pymchat_adapter import PymChatAdapter


class PymChatMessageEvent(AstrMessageEvent):
    """Message event for PymChat chatroom.

    This event class handles chat interactions.
    """

    def __init__(
        self,
        message_str: str,
        message_obj,
        platform_meta,
        session_id: str,
        adapter: PymChatAdapter,
        chatroom_id: str | None = None,
        need_ai_reply: bool = False,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self._adapter = adapter
        self._chatroom_id = chatroom_id
        self.set_extra("need_ai_reply", need_ai_reply)

    @property
    def adapter(self) -> PymChatAdapter:
        """获取适配器实例"""
        return self._adapter

    @property
    def chatroom_id(self) -> str | None:
        """获取关联的聊天室 ID"""
        return self._chatroom_id

    async def send(self, message: MessageChain | None):
        """处理框架发送，普通聊天室场景直接发送"""
        if message is None or not message.chain:
            await super().send(message)
            return

        text = message.get_plain_text().strip()
        if not text:
            await super().send(message)
            return

        # 普通聊天室场景，直接发送
        if self._chatroom_id:
            await self._adapter.send_to_chatroom(self._chatroom_id, text)
        else:
            await self._adapter.send_to_chatroom("public", text)

        logger.debug(f"[PymChat] 发送消息: {text[:50]}...")