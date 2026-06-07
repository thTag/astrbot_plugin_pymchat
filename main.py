import asyncio
import aiohttp
import re
from typing import Optional

from astrbot.api.star import Star, Context, register
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent


@register(
    "astrbot_plugin_pymchat",
    "叹号大帝",
    "PymChat 聊天室插件（纯插件模式，支持自定义人设、自动获取昵称）",
    "v1.0.0",
    "https://github.com/thTag/astrbot_plugin_pymchat"
)
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)
        # 基础配置
        self.username = config.get("username")
        self.password = config.get("password")
        self.api_base = config.get("api_base", "https://chat.qplm.xyz/api/ac.php")
        self.login_url = config.get("login_url", "https://chat.qplm.xyz/api/login.php")
        self.poll_interval = config.get("poll_interval", 3)
        
        # 触发配置
        self.configured_bot_name = config.get("bot_name", "bot").lower()
        self.trigger_keyword = config.get("trigger_keyword", "th").lower()
        self.browser_id = config.get("browser_id", "astrbot_pymchat")
        self.enable_llm_reply = config.get("enable_llm_reply", True)
        self.persona = config.get("persona", "你是一个友好、乐于助人的机器人助手。")
        
        # 昵称自动获取与同步开关
        self.auto_fetch_nickname = config.get("auto_fetch_nickname", True)
        self.sync_bot_name = config.get("sync_bot_name", False)
        
        # 运行时变量
        self.bot_name = self.configured_bot_name
        self.api_key = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._poll_task = None
        self._last_msg_id = 0
        self._processed_ids = set()
    
    # ==================== 生命周期 ====================
    async def on_load(self):
        if not self.username or not self.password:
            logger.error("[PymChat] 未配置用户名或密码，请在插件配置中填写")
            return
        
        self.session = aiohttp.ClientSession()
        if not await self._login():
            logger.error("[PymChat] 登录失败，插件无法启动")
            await self.session.close()
            return
        
        await self._fetch_and_apply_nickname()
        
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())
        logger.info(f"[PymChat] 插件已启动，Bot 昵称: {self.bot_name}，触发词: {self.trigger_keyword}")
    
    async def on_unload(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        if self.session:
            await self.session.close()
        logger.info("[PymChat] 插件已卸载")
    
    # ==================== 控制指令（修正版） ====================
    @filter.command("pymchat")
    async def command_status(self, event: AstrMessageEvent):
        # 获取参数列表（标准方法）
        args = event.get_args()
        
        if args:
            subcmd = args[0].lower()
            if subcmd == "reload":
                self.api_key = None
                if await self._login():
                    await self._fetch_and_apply_nickname()
                    yield event.plain_result("✅ PymChat 重新登录成功，昵称已刷新")
                else:
                    yield event.plain_result("❌ 重新登录失败，请检查用户名密码")
                return
            elif subcmd == "sync_nickname":
                if not self.api_key:
                    yield event.plain_result("❌ 未登录，请先使用 /pymchat reload")
                    return
                if await self._fetch_and_apply_nickname():
                    yield event.plain_result(f"✅ 昵称已同步为: {self.bot_name}")
                else:
                    yield event.plain_result("❌ 昵称同步失败")
                return
            elif subcmd == "update_nickname":
                if not self.api_key:
                    yield event.plain_result("❌ 未登录，请先使用 /pymchat reload")
                    return
                new_nick = self.configured_bot_name
                if await self._update_nickname_on_pymchat(new_nick):
                    self.bot_name = new_nick
                    yield event.plain_result(f"✅ 已向 PymChat 提交昵称更新，新昵称: {new_nick}")
                else:
                    yield event.plain_result("❌ 更新昵称失败，请检查昵称长度（2-20字符）或 API Key")
                return
            else:
                yield event.plain_result(f"未知子命令: {subcmd}\n可用: reload, sync_nickname, update_nickname")
                return
        
        # 无子命令，显示状态
        nickname_source = "自动获取" if (self.auto_fetch_nickname and self.bot_name != self.configured_bot_name) else "用户配置"
        yield event.plain_result(
            f"PymChat 插件状态\n"
            f"- 轮询: {'✅ 运行中' if self._running else '⏹️ 已停止'}\n"
            f"- Bot 昵称: {self.bot_name} (来源: {nickname_source})\n"
            f"- 最后消息ID: {self._last_msg_id}\n"
            f"- 已处理消息数: {len(self._processed_ids)}\n"
            f"- 当前人设: {self.persona[:50]}..."
        )
    
    # ==================== 核心 API 交互 ====================
    async def _login(self) -> bool:
        login_data = {"username": self.username, "password": self.password}
        try:
            async with self.session.post(self.login_url, json=login_data) as resp:
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
    
    async def _fetch_user_profile(self) -> Optional[dict]:
        if not self.api_key:
            return None
        params = {
            "api_key": self.api_key,
            "action": "get_profile",
            "browser_id": self.browser_id,
        }
        try:
            async with self.session.get(self.api_base, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == 200 and "data" in data:
                        return data["data"]
                    else:
                        logger.warning(f"[PymChat] 获取个人信息失败: {data.get('message')}")
                elif resp.status == 401:
                    logger.warning("[PymChat] API Key 失效")
                    self.api_key = None
        except Exception as e:
            logger.error(f"[PymChat] 获取个人信息异常: {e}")
        return None
    
    async def _update_nickname_on_pymchat(self, new_nickname: str) -> bool:
        if not self.api_key:
            return False
        if len(new_nickname) < 2 or len(new_nickname) > 20:
            logger.warning(f"[PymChat] 昵称长度 {len(new_nickname)} 不合法，应为2-20字符")
            return False
        params = {
            "api_key": self.api_key,
            "action": "update_profile",
            "display_name": new_nickname,
            "browser_id": self.browser_id,
        }
        try:
            async with self.session.get(self.api_base, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == 200:
                        logger.info(f"[PymChat] 昵称更新成功: {new_nickname}")
                        return True
                    else:
                        logger.warning(f"[PymChat] 更新昵称失败: {data.get('message')}")
                elif resp.status == 401:
                    logger.warning("[PymChat] API Key 失效")
                    self.api_key = None
        except Exception as e:
            logger.error(f"[PymChat] 更新昵称异常: {e}")
        return False
    
    async def _fetch_and_apply_nickname(self) -> bool:
        if not self.auto_fetch_nickname:
            self.bot_name = self.configured_bot_name
            return True
        profile = await self._fetch_user_profile()
        if profile and profile.get("display_name"):
            self.bot_name = profile["display_name"].lower()
            logger.info(f"[PymChat] 自动获取昵称成功: {self.bot_name}")
            return True
        else:
            logger.warning("[PymChat] 自动获取昵称失败，使用配置的 bot_name")
            self.bot_name = self.configured_bot_name
            return False
    
    # ==================== 消息轮询与处理 ====================
    async def _poll_messages(self):
        consecutive_errors = 0
        while self._running:
            if not self.api_key:
                if not await self._login():
                    await asyncio.sleep(60)
                    continue
            
            try:
                messages = await self._fetch_new_messages()
                consecutive_errors = 0
                for raw in messages:
                    msg_id = raw.get("id")
                    if not msg_id or msg_id in self._processed_ids:
                        continue
                    
                    content = raw.get("content", "")
                    sender = raw.get("sn") or raw.get("sid", "")
                    sender_id = raw.get("sid", "")
                    chatroom_id = raw.get("rid", "public")
                    
                    if self._should_trigger(content):
                        clean_content = self._clean_message(content)
                        if clean_content:
                            logger.info(f"[PymChat] 触发消息 from {sender}: {clean_content[:50]}")
                            if self.enable_llm_reply:
                                asyncio.create_task(self._generate_and_reply(
                                    user_message=clean_content,
                                    sender_name=sender,
                                    sender_id=sender_id,
                                    chatroom_id=chatroom_id
                                ))
                    
                    self._processed_ids.add(msg_id)
                    if len(self._processed_ids) > 10000:
                        self._processed_ids.clear()
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"[PymChat] 轮询失败 ({consecutive_errors}): {e}")
                if consecutive_errors >= 5:
                    logger.warning("[PymChat] 连续失败，尝试重新登录")
                    self.api_key = None
                    consecutive_errors = 0
                    await asyncio.sleep(10)
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_new_messages(self) -> list:
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
                        msgs = msg_data.get("messages", [])
                        if msgs and "last_id" in msg_data:
                            self._last_msg_id = msg_data["last_id"]
                        return msgs
                elif resp.status == 401:
                    logger.warning("[PymChat] API Key 失效")
                    self.api_key = None
        except Exception as e:
            logger.error(f"[PymChat] 拉取消息异常: {e}")
        return []
    
    def _should_trigger(self, content: str) -> bool:
        if not content:
            return False
        lower_content = content.lower()
        return f"@{self.bot_name}" in lower_content or self.trigger_keyword in lower_content
    
    def _clean_message(self, content: str) -> str:
        clean = content
        clean = re.sub(rf"@{re.escape(self.bot_name)}", "", clean, flags=re.IGNORECASE)
        clean = re.sub(rf"\b{re.escape(self.trigger_keyword)}\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean
    
    async def _generate_and_reply(self, user_message: str, sender_name: str, sender_id: str, chatroom_id: str):
        try:
            provider_id = await self.context.get_current_chat_provider_id()
            if not provider_id:
                logger.warning("[PymChat] 未找到可用的聊天模型 ID")
                return
            
            prompt = f"{self.persona}\n用户 {sender_name} 说：{user_message}\n请基于你的人设回复用户（简短自然，不要@任何人）："
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            if hasattr(llm_resp, 'completion_text'):
                reply_text = llm_resp.completion_text.strip()
            elif isinstance(llm_resp, str):
                reply_text = llm_resp.strip()
            else:
                return
            
            if reply_text:
                await self._send_message(chatroom_id, reply_text)
                logger.info(f"[PymChat] 已回复 {sender_name}: {reply_text[:50]}")
        except Exception as e:
            logger.error(f"[PymChat] LLM 生成回复失败: {e}")
    
    async def _send_message(self, chatroom_id: str, content: str):
        if not self.api_key:
            return
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
                    if data.get("status") == 200:
                        logger.info(f"[PymChat] 消息发送成功: {content[:30]}...")
                    else:
                        logger.error(f"[PymChat] 发送失败: {data.get('message')}")
                elif resp.status == 429:
                    logger.warning("[PymChat] 触发速率限制，等待150秒")
                    await asyncio.sleep(150)
        except Exception as e:
            logger.error(f"[PymChat] 发送异常: {e}")