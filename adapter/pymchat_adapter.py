import asyncio
import aiohttp
import random
import re
from typing import Any

from astrbot import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.api.platform import (
    AstrBotMessage,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.core.platform.astr_message_event import MessageSesion

from .pymchat_event import PymChatMessageEvent

PYMCHAT_DEFAULT_CONFIG_TMPL = {
    "username": "",  # PymChat 登录用户名
    "password": "",  # PymChat 登录密码
    "api_base": "https://chat.qplm.xyz/api/ac.php",
    "login_url": "https://chat.qplm.xyz/api/login.php",
    "poll_interval": 3,
    "bot_name": "bot",
    "trigger_keyword": "th",
    "browser_id": "astrbot_pymchat",
}


@register_platform_adapter("pymchat", "PymChat 平台适配器")
class PymChatAdapter(Platform):
    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue):
        super().__init__(event_queue)
        self.platform_config = platform_config
        self.platform_settings = platform_settings

        # 读取配置（完全参照 astrbook）
        self.username = platform_config.get("username", "")
        self.password = platform_config.get("password", "")
        self.api_base = platform_config.get("api_base", "https://chat.qplm.xyz/api/ac.php")
        self.login_url = platform_config.get("login_url", "https://chat.qplm.xyz/api/login.php")
        self.poll_interval = platform_config.get("poll_interval", 3)
        self.bot_name = platform_config.get("bot_name", "bot")
        self.trigger_keyword = platform_config.get("trigger_keyword", "th")
        self.browser_id = platform_config.get("browser_id", "astrbot_pymchat")

        # 状态变量
        self.api_key = None
        self.session = None
        self._running = False
        self._poll_task = None
        self._last_msg_id = 0
        self._processed_ids = set()

    def meta(self) -> PlatformMetadata:
        """提供平台元信息"""
        return PlatformMetadata("pymchat", "PymChat 平台适配器")

    async def run(self):
        """启动适配器"""
        if not self.username or not self.password:
            logger.error("[PymChat] 未配置用户名或密码")
            return

        # 创建 HTTP 会话
        self.session = aiohttp.ClientSession()

        # 登录获取 API Key
        if not await self._ensure_valid_api_key():
            logger.error("[PymChat] 无法获取 API Key")
            await self.session.close()
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())
        logger.info("[PymChat] 适配器已启动")

    async def stop(self):
        """停止适配器"""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        if self.session:
            await self.session.close()
        logger.info("[PymChat] 适配器已停止")

    async def send_by_session(self, session: MessageSesion, message_chain: MessageChain):
        """发送消息（AstrBot 通过此方法回复）
        注意：在 PymChat 场景下，我们主要通过 LLM 工具的 send_to_chatroom 来发送，
        此方法保留以兼容框架调用。
        """
        content = self._extract_text(message_chain)
        if not content:
            return
        if len(content) > 500:
            content = content[:500]

        if not await self._ensure_valid_api_key():
            return

        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "browser_id": self.browser_id,
        }

        try:
            async with self.session.get(self.api_base, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == 200:
                        logger.info(f"[PymChat] 消息发送成功: {content[:30]}...")
                    else:
                        logger.error(f"[PymChat] 发送失败: {data.get('message')}")
                elif resp.status == 429:
                    logger.warning("[PymChat] 触发速率限制，等待150秒...")
                    await asyncio.sleep(150)
        except Exception as e:
            logger.error(f"[PymChat] 发送消息异常: {e}")

    async def _poll_messages(self):
        """轮询公共聊天室新消息"""
        consecutive_errors = 0
        while self._running:
            if not await self._ensure_valid_api_key():
                await asyncio.sleep(60)
                continue

            try:
                messages = await self._fetch_new_messages()
                consecutive_errors = 0
                for raw in messages:
                    msg_id = raw.get("id")
                    if not msg_id or msg_id in self._processed_ids:
                        continue

                    # 构造 AstrBotMessage
                    ab_msg = AstrBotMessage()
                    ab_msg.content = raw.get("content", "")
                    ab_msg.sender = raw.get("sn") or raw.get("sid", "")
                    ab_msg.sender_id = raw.get("sid", "")
                    ab_msg.target = raw.get("rid", "public")
                    ab_msg.message_id = str(msg_id)
                    ab_msg.raw = raw

                    # 检查是否触发 @bot 或关键词
                    content_lower = ab_msg.content.lower()
                    bot_name_lower = self.bot_name.lower()
                    need_ai_reply = (
                        f"@{bot_name_lower}" in content_lower
                        or self.trigger_keyword.lower() in content_lower
                    )

                    if need_ai_reply:
                        # 清洗消息内容：移除 @bot 和触发关键词
                        clean_content = ab_msg.content
                        clean_content = re.sub(
                            rf"@{re.escape(self.bot_name)}", "", clean_content, flags=re.IGNORECASE
                        )
                        clean_content = re.sub(
                            rf"\b{re.escape(self.trigger_keyword)}\b",
                            "",
                            clean_content,
                            flags=re.IGNORECASE,
                        )
                        clean_content = re.sub(r"\s+", " ", clean_content).strip()
                        if clean_content:
                            ab_msg.content = clean_content

                    # 创建自定义事件
                    event = PymChatMessageEvent(
                        message_str=ab_msg.content,
                        message_obj=ab_msg,
                        platform_meta={"platform": "pymchat"},
                        session_id=ab_msg.sender_id,
                        adapter=self,
                        chatroom_id=ab_msg.target,
                        need_ai_reply=need_ai_reply,
                    )
                    await self._event_queue.put(event)
                    self._processed_ids.add(msg_id)

                    if len(self._processed_ids) > 10000:
                        self._processed_ids.clear()

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"[PymChat] 轮询消息失败 (错误计数 {consecutive_errors}): {e}")
                if consecutive_errors >= 5:
                    logger.error("[PymChat] 连续5次轮询失败，尝试重新登录...")
                    self.api_key = None
                    consecutive_errors = 0
                    await asyncio.sleep(10)
                    continue

            await asyncio.sleep(self.poll_interval)

    async def _fetch_new_messages(self) -> list:
        """获取公共聊天室的新消息"""
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "public",
            "limit": 20,
        }
        if self._last_msg_id:
            params["last_id"] = self._last_msg_id

        try:
            async with self.session.get(self.api_base, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == 200 and "data" in data:
                        msg_data = data["data"]
                        messages = msg_data.get("messages", [])
                        if messages and "last_id" in msg_data:
                            self._last_msg_id = msg_data["last_id"]
                        return messages
                elif resp.status == 401:
                    logger.warning("[PymChat] API Key 失效")
                    self.api_key = None
        except Exception as e:
            logger.error(f"[PymChat] 拉取消息异常: {e}")
        return []

    async def _ensure_valid_api_key(self) -> bool:
        """确保 API Key 有效，失效则重新登录"""
        if not self.api_key:
            return await self._login_and_get_api_key()
        return True

    async def _login_and_get_api_key(self) -> bool:
        """使用用户名密码登录，获取 API Key"""
        login_data = {"username": self.username, "password": self.password}
        try:
            async with self.session.post(self.login_url, json=login_data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("status") == 200:
                        self.api_key = result["data"]["api_key"]
                        logger.info("[PymChat] 登录成功，API Key 已获取")
                        return True
                    else:
                        logger.error(f"[PymChat] 登录失败: {result.get('message')}")
                else:
                    logger.error(f"[PymChat] 登录请求失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] 登录异常: {e}")
        return False

    def _extract_text(self, message_chain: MessageChain) -> str:
        """从 MessageChain 中提取纯文本"""
        parts = []
        for comp in message_chain.chain:
            if isinstance(comp, Plain):
                parts.append(comp.text)
        return "".join(parts)

    # ---------- 对外供工具调用的方法 ----------
    async def send_to_chatroom(self, chatroom_id: str, content: str) -> bool:
        """发送消息到聊天室，供 LLM 工具调用"""
        if not await self._ensure_valid_api_key():
            return False
        if len(content) > 500:
            content = content[:500]

        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "browser_id": self.browser_id,
        }
        if chatroom_id and chatroom_id != "public":
            params["target"] = chatroom_id

        try:
            async with self.session.get(self.api_base, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status") == 200
        except Exception as e:
            logger.error(f"[PymChat] send_to_chatroom 异常: {e}")
        return False

    async def send_private_message(self, recipient_id: str, content: str) -> bool:
        """发送私信，供 LLM 工具调用"""
        if not await self._ensure_valid_api_key():
            return False
        if len(content) > 500:
            content = content[:500]

        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": recipient_id,
            "browser_id": self.browser_id,
        }

        try:
            async with self.session.get(self.api_base, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status") == 200
        except Exception as e:
            logger.error(f"[PymChat] send_private_message 异常: {e}")
        return False