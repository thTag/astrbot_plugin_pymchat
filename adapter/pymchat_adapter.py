import asyncio
import aiohttp
import re
from typing import Dict, Any, List, Optional

# 修正导入：使用 astrbot.api.message_components 而不是 astrbot.api.message
from astrbot.api.message_components import MessageChain, Plain
from astrbot.api.platform import Platform, AstrBotMessage, PlatformMetadata, register_platform_adapter
from astrbot.api.event import MessageSession
from astrbot.api import logger

@register_platform_adapter(
    "pymchat",
    "PymChat 平台适配器"
)
class PymChatAdapter(Platform):
    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue):
        super().__init__(event_queue)
        self.platform_config = platform_config
        self.platform_settings = platform_settings

        # 读取配置
        self.username = platform_config.get("username")
        self.password = platform_config.get("password")
        self.api_base = platform_config.get("api_base", "https://chat.qplm.xyz/api/ac.php")
        self.login_url = platform_config.get("login_url", "https://chat.qplm.xyz/api/login.php")
        self.poll_interval = platform_config.get("poll_interval", 3)
        self.bot_name = platform_config.get("bot_name", "bot")
        self.trigger_keyword = platform_config.get("trigger_keyword", "th")
        self.browser_id = platform_config.get("browser_id", "astrbot_pymchat")

        self.api_key = None
        self._running = False
        self._poll_task = None
        self._last_msg_id = 0
        self._processed_ids = set()

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata("pymchat", "PymChat 平台适配器")

    async def run(self):
        if not self.username or not self.password:
            logger.error("[PymChat] 未配置用户名或密码")
            return
        if not await self._ensure_valid_api_key():
            logger.error("[PymChat] 无法获取 API Key")
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())
        logger.info("[PymChat] 适配器已启动")

    async def send_by_session(self, session: MessageSession, message_chain: MessageChain):
        """发送消息"""
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
            "browser_id": self.browser_id
        }
        if session.contact_id:
            params["target"] = session.contact_id

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(self.api_base, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == 200:
                            logger.info(f"[PymChat] 消息发送成功: {content[:30]}...")
                        else:
                            logger.error(f"[PymChat] 发送失败: {data.get('message')}")
                    elif resp.status == 429:
                        logger.warning("[PymChat] 触发速率限制，等待150秒")
                        await asyncio.sleep(150)
        except Exception as e:
            logger.error(f"[PymChat] 发送异常: {e}")

    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        logger.info("[PymChat] 适配器已停止")

    # ---------- 内部方法 ----------
    async def _poll_messages(self):
        while self._running:
            if not await self._ensure_valid_api_key():
                await asyncio.sleep(60)
                continue
            messages = await self._fetch_new_messages()
            for raw in messages:
                msg_id = raw.get("id")
                if not msg_id or msg_id in self._processed_ids:
                    continue
                ab_msg = AstrBotMessage()
                ab_msg.content = raw.get("content", "")
                ab_msg.sender = raw.get("sn") or raw.get("sid", "")
                ab_msg.sender_id = raw.get("sid", "")
                ab_msg.target = raw.get("rid", "public")
                ab_msg.message_id = str(msg_id)
                ab_msg.raw = raw

                session = MessageSession(
                    session_id=raw.get("sid", "unknown"),
                    platform_session_id=raw.get("sid", "unknown"),
                    contact_id=ab_msg.target,
                    message=ab_msg
                )
                await self._event_queue.put(session)
                self._processed_ids.add(msg_id)
                if len(self._processed_ids) > 10000:
                    self._processed_ids.clear()
            await asyncio.sleep(self.poll_interval)

    async def _fetch_new_messages(self) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "public",
            "limit": 20
        }
        if self._last_msg_id:
            params["last_id"] = self._last_msg_id
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_base, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == 200 and "data" in data:
                            msg_data = data["data"]
                            messages = msg_data.get("messages", [])
                            if messages and "last_id" in msg_data:
                                self._last_msg_id = msg_data["last_id"]
                            return messages
        except Exception as e:
            logger.error(f"[PymChat] 拉取消息异常: {e}")
        return []

    async def _ensure_valid_api_key(self) -> bool:
        if not self.api_key:
            return await self._login_and_get_api_key()
        if not await self._test_api_key():
            logger.warning("[PymChat] API Key 失效，重新登录")
            self.api_key = None
            return await self._login_and_get_api_key()
        return True

    async def _login_and_get_api_key(self) -> bool:
        data = {"username": self.username, "password": self.password}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.login_url, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("status") == 200:
                            self.api_key = result["data"]["api_key"]
                            logger.info("[PymChat] 登录成功")
                            return True
                        else:
                            logger.error(f"[PymChat] 登录失败: {result.get('message')}")
                    else:
                        logger.error(f"[PymChat] 登录请求失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] 登录异常: {e}")
        return False

    async def _test_api_key(self) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "public",
            "limit": 1
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_base, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("status") != 401
        except Exception:
            return False
        return False

    def _extract_text(self, message_chain: MessageChain) -> str:
        parts = []
        for comp in message_chain:
            if isinstance(comp, Plain):
                parts.append(comp.text)
        return "".join(parts)