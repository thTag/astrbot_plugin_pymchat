import asyncio
import aiohttp
from typing import Optional, Dict, Any, List
from astrbot.api.platform import PlatformAdapter, AstrBotMessage, PlatformEvent, register_platform_adapter, PlatformCapabilities
from astrbot.api.message_components import Plain
from astrbot.api import logger
import re

@register_platform_adapter(
    name="pymchat",
    display_name="PymChat",
    description="PymChat 公共聊天室适配器",
    capabilities=PlatformCapabilities.SEND_MESSAGE | PlatformCapabilities.REPLY
)
class PymChatAdapter(PlatformAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.username = config.get("username")
        self.password = config.get("password")
        self.api_base = config.get("api_base", "https://chat.qplm.xyz/api/ac.php")
        self.qunliao_base = config.get("qunliao_base", "https://chat.qplm.xyz/qunliao/api.php")
        self.login_url = config.get("login_url", "https://chat.qplm.xyz/api/login.php")
        self.poll_interval = config.get("poll_interval", 3)  # 建议至少3秒[reference:6]
        self.bot_name = config.get("bot_name", "bot")  # Bot的昵称，用于检测@
        self.trigger_keyword = config.get("trigger_keyword", "th")  # 触发关键词
        self._running = False
        self._poll_task = None
        self._last_msg_id = None
        self._processed_ids = set()
        self.api_key = None
        self.browser_id = config.get("browser_id", "astrbot_pymchat")  # 浏览器标识[reference:7]

    async def start(self):
        """启动适配器：登录获取 API Key，开始轮询"""
        logger.info(f"[PymChat] 适配器启动，API: {self.api_base}")
        if not self.username or not self.password:
            logger.error("[PymChat] 未配置用户名或密码，无法获取 API Key")
            return
        if not await self._ensure_valid_api_key():
            logger.error("[PymChat] 无法获取有效的 API Key，适配器启动失败")
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())

    async def stop(self):
        """停止适配器"""
        logger.info("[PymChat] 适配器停止")
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def send_message(self, message: AstrBotMessage):
        """发送消息到 PymChat（自动识别目标类型）"""
        content = self._extract_text(message)
        if not content:
            logger.warning("[PymChat] 消息内容为空，跳过发送")
            return
        if len(content) > 500:
            logger.warning("[PymChat] 消息内容超过500字符限制，已截断")
            content = content[:500]

        if not await self._ensure_valid_api_key():
            logger.error("[PymChat] 发送消息失败：API Key 无效")
            return

        # 判断目标类型
        target_type = getattr(message, 'target_type', 'public')
        target_id = message.target

        if target_type == 'private':
            # 发送私信[reference:8]
            await self._send_private_message(target_id, content)
        elif target_type == 'group':
            # 发送群消息（POST请求）[reference:9]
            await self._send_group_message(target_id, content)
        else:
            # 发送公共消息
            await self._send_public_message(content)

    async def _send_public_message(self, content: str):
        """发送公共消息[reference:10]"""
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "browser_id": self.browser_id
        }
        await self._http_get_with_retry(self.api_base, params, "公共消息")

    async def _send_private_message(self, recipient_id: str, content: str):
        """发送私信[reference:11]"""
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": recipient_id,
            "browser_id": self.browser_id
        }
        await self._http_get_with_retry(self.api_base, params, f"私信给 {recipient_id}")

    async def _send_group_message(self, group_id: str, content: str):
        """发送群消息（POST请求）[reference:12]"""
        data = {
            "api_key": self.api_key,
            "action": "send_message",
            "group_id": group_id,
            "content": content,
            "browser_id": self.browser_id
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.qunliao_base, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("status") == 200:
                            logger.info(f"[PymChat] 群消息发送成功: {content[:30]}...")
                        else:
                            logger.error(f"[PymChat] 群消息发送失败: {result.get('message')}")
                    elif resp.status == 429:
                        logger.warning("[PymChat] 触发速率限制，等待150秒...")
                        await asyncio.sleep(150)
                    else:
                        logger.error(f"[PymChat] 群消息发送失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] 群消息发送异常: {e}")

    async def _http_get_with_retry(self, url: str, params: dict, action_desc: str):
        """带429重试的HTTP GET请求"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("status") == 200:
                            logger.info(f"[PymChat] {action_desc}发送成功")
                        else:
                            logger.error(f"[PymChat] {action_desc}发送失败: {result.get('message')}")
                    elif resp.status == 429:
                        logger.warning(f"[PymChat] {action_desc}触发速率限制，等待150秒...")
                        await asyncio.sleep(150)
                        # 重试一次
                        await self._http_get_with_retry(url, params, action_desc)
                    else:
                        logger.error(f"[PymChat] {action_desc}发送失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] {action_desc}发送异常: {e}")

    async def _ensure_valid_api_key(self) -> bool:
        """确保 API Key 有效，失效则重新登录获取"""
        if not self.api_key:
            return await self._login_and_get_api_key()
        if not await self._test_api_key():
            logger.warning("[PymChat] API Key 已失效，尝试重新登录...")
            self.api_key = None
            return await self._login_and_get_api_key()
        return True

    async def _login_and_get_api_key(self) -> bool:
        """使用用户名密码登录，获取并存储 API Key[reference:13]"""
        login_data = {"username": self.username, "password": self.password}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.login_url, json=login_data, headers={"Content-Type": "application/json"}) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("status") == 200:
                            self.api_key = result["data"]["api_key"]
                            expires_at = result["data"].get("expires_at")
                            logger.info(f"[PymChat] 登录成功，API Key 有效期至: {expires_at}")
                            return True
                        else:
                            logger.error(f"[PymChat] 登录失败: {result.get('message')}")
                    else:
                        logger.error(f"[PymChat] 登录请求失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] 登录异常: {e}")
        return False

    async def _test_api_key(self) -> bool:
        """测试当前 API Key 是否有效"""
        params = {"api_key": self.api_key, "action": "get_messages", "type": "public", "limit": 1}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_base, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("status") != 401
                    return False
        except Exception:
            return False

    async def _poll_messages(self):
        """轮询新消息并转换为 AstrBot 事件"""
        consecutive_errors = 0
        while self._running:
            if not await self._ensure_valid_api_key():
                logger.error("[PymChat] API Key 无效，等待重试...")
                await asyncio.sleep(60)
                continue

            try:
                messages = await self._fetch_new_messages()
                consecutive_errors = 0  # 重置错误计数
                for raw_msg in messages:
                    msg_id = raw_msg.get("id")
                    if not msg_id or msg_id in self._processed_ids:
                        continue
                    ab_msg = self._convert_to_astrbot_message(raw_msg)
                    if ab_msg:
                        self._processed_ids.add(msg_id)
                        if len(self._processed_ids) > 10000:
                            self._processed_ids.clear()
                        event = PlatformEvent(platform="pymchat", message=ab_msg)
                        await self.commit_event(event)
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

    async def _fetch_new_messages(self) -> List[Dict]:
        """获取公共聊天室的新消息（增量）[reference:14]"""
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
                        else:
                            logger.warning(f"[PymChat] API 返回错误: {data.get('message')}")
                    else:
                        logger.warning(f"[PymChat] 获取消息失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[PymChat] 拉取消息异常: {e}")
        return []

    def _convert_to_astrbot_message(self, raw: Dict) -> Optional[AstrBotMessage]:
        """将 PymChat 原始消息转换为 AstrBotMessage，并检测触发条件"""
        try:
            ab_msg = AstrBotMessage()
            ab_msg.content = raw.get("content", "")
            ab_msg.sender = raw.get("sn") or raw.get("sid", "")
            ab_msg.sender_id = raw.get("sid", "")
            ab_msg.target = raw.get("rid", "public")
            ab_msg.message_id = str(raw.get("id", ""))
            ab_msg.raw = raw

            # 触发式AI回复检测
            if self._should_trigger_ai(ab_msg):
                # 提取纯净消息（去除@bot和关键词）
                clean_content = self._extract_clean_content(ab_msg.content)
                if clean_content:
                    ab_msg.content = clean_content
                    # 标记需要AI回复
                    ab_msg.need_ai_reply = True
                    logger.info(f"[PymChat] 检测到触发条件，将回复用户: {ab_msg.sender}，内容: {clean_content[:50]}")

            return ab_msg
        except Exception as e:
            logger.error(f"[PymChat] 消息转换失败: {e}")
            return None

    def _should_trigger_ai(self, message: AstrBotMessage) -> bool:
        """检测是否触发AI回复：@bot 或 包含关键词"th"【用户需求】"""
        content = message.content.lower()
        # 检测 @bot
        if f"@{self.bot_name.lower()}" in content:
            return True
        # 检测触发关键词
        if self.trigger_keyword.lower() in content:
            return True
        return False

    def _extract_clean_content(self, content: str) -> str:
        """提取纯净消息内容（移除@bot和触发关键词）"""
        # 移除 @bot
        clean = re.sub(rf'@{re.escape(self.bot_name)}', '', content, flags=re.IGNORECASE)
        # 移除触发关键词"th"（作为独立单词移除，避免误删）
        clean = re.sub(r'\bth\b', '', clean, flags=re.IGNORECASE)
        # 清理多余空格
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def _extract_text(self, message: AstrBotMessage) -> str:
        """从 AstrBotMessage 中提取纯文本"""
        parts = [comp.text for comp in message.message if isinstance(comp, Plain)]
        return "".join(parts)