import asyncio
import aiohttp
from typing import Dict, Any, List, Optional
from astrbot.core.platform import Platform, AstrMessageEvent, AstrBotMessage
from astrbot.core.message.components import Plain
from astrbot.api import logger
from astrbot.api.event import filter

class PymChatAdapter(Platform):
    def __init__(self, config: dict, event_queue: asyncio.Queue):
        super().__init__(config, event_queue)
        self.username = config.get("username")
        self.password = config.get("password")
        self.api_base = config.get("api_base", "https://chat.qplm.xyz/api/ac.php")
        self.login_url = config.get("login_url", "https://chat.qplm.xyz/api/login.php")
        self.poll_interval = config.get("poll_interval", 3)
        self.bot_name = config.get("bot_name", "bot")
        self.trigger_keyword = config.get("trigger_keyword", "th")
        self.api_key = None
        self._poll_task = None
        self._running = False
        self._last_msg_id = 0
        self._processed_ids = set()
        self.browser_id = config.get("browser_id", "astrbot_pymchat")
    
    async def run(self):
        if not self.username or not self.password:
            logger.error("[PymChat] 用户名或密码未配置")
            return
        if not await self._ensure_valid_api_key():
            logger.error("[PymChat] 无法获取API Key")
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())
        logger.info("[PymChat] 适配器运行中")
    
    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
    
    async def send(self, message: AstrMessageEvent):
        content = self._extract_text(message.message_obj)
        if not content:
            return
        if len(content) > 500:
            content = content[:500]
        if not await self._ensure_valid_api_key():
            return
        params = {"api_key": self.api_key, "action": "send_message", "content": content, "browser_id": self.browser_id}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_base, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == 200:
                            logger.info(f"[PymChat] 消息发送成功: {content[:30]}")
                        else:
                            logger.error(f"[PymChat] 发送失败: {data.get('message')}")
                    elif resp.status == 429:
                        logger.warning("[PymChat] 触发速率限制，等待150秒...")
                        await asyncio.sleep(150)
        except Exception as e:
            logger.error(f"[PymChat] 发送异常: {e}")

    async def _ensure_valid_api_key(self) -> bool:
        if not self.api_key:
            return await self._login_and_get_api_key()
        if not await self._test_api_key():
            logger.warning("[PymChat] API Key 失效，重新登录...")
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
                            logger.info("[PymChat] 登录成功，API Key已获取")
                            return True
                        else:
                            logger.error(f"[PymChat] 登录失败: {result.get('message')}")
                    else:
                        logger.error(f"[PymChat] 登录请求失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] 登录异常: {e}")
        return False

    async def _test_api_key(self) -> bool:
        params = {"api_key": self.api_key, "action": "get_messages", "type": "public", "limit": 1}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_base, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("status") != 401
        except Exception:
            return False
        return False

    async def _poll_messages(self):
        while self._running:
            if not await self._ensure_valid_api_key():
                await asyncio.sleep(60)
                continue
            messages = await self._fetch_new_messages()
            for raw_msg in messages:
                msg_id = raw_msg.get("id")
                if not msg_id or msg_id in self._processed_ids:
                    continue
                # 构建 AstrBotMessage
                ab_msg = AstrBotMessage()
                ab_msg.content = raw_msg.get("content", "")
                ab_msg.sender = raw_msg.get("sn") or raw_msg.get("sid", "")
                ab_msg.sender_id = raw_msg.get("sid", "")
                ab_msg.message_id = str(msg_id)
                ab_msg.raw = raw_msg
                # 构造事件并提交到队列
                event = AstrMessageEvent(
                    platform=self.platform_name,
                    message=ab_msg,
                    session_id=raw_msg.get("sid", "unknown"),
                    platform_session_id=raw_msg.get("sid", "unknown"),
                )
                await self._event_queue.put(event)
                self._processed_ids.add(msg_id)
                if len(self._processed_ids) > 10000:
                    self._processed_ids.clear()
            await asyncio.sleep(self.poll_interval)

    async def _fetch_new_messages(self) -> List[Dict]:
        params = {"api_key": self.api_key, "action": "get_messages", "type": "public", "limit": 20}
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

    def _extract_text(self, message: AstrBotMessage) -> str:
        return "".join([comp.text for comp in message.message if isinstance(comp, Plain)])