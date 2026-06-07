import asyncio
import aiohttp
import re
from typing import Optional

from astrbot.api.star import Star, Context, register
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent


@register(
    "astrbot_plugin_pymchat",
    "叹点",
    "PymChat 聊天室插件（纯插件模式，支持自定义人设）",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_pymchat"
)
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)
        # 读取配置
        self.username = config.get("username")
        self.password = config.get("password")
        self.api_base = config.get("api_base", "https://chat.qplm.xyz/api/ac.php")
        self.login_url = config.get("login_url", "https://chat.qplm.xyz/api/login.php")
        self.poll_interval = config.get("poll_interval", 3)
        self.bot_name = config.get("bot_name", "bot").lower()
        self.trigger_keyword = config.get("trigger_keyword", "th").lower()
        self.browser_id = config.get("browser_id", "astrbot_pymchat")
        self.enable_llm_reply = config.get("enable_llm_reply", True)
        self.persona = config.get("persona", "你是一个友好、乐于助人的机器人助手。")
        
        self.api_key = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._poll_task = None
        self._last_msg_id = 0
        self._processed_ids = set()
    
    async def on_load(self):
        """插件加载：登录并启动轮询"""
        if not self.username or not self.password:
            logger.error("[PymChat] 未配置用户名或密码，请在插件配置中填写")
            return
        
        self.session = aiohttp.ClientSession()
        if not await self._login():
            logger.error("[PymChat] 登录失败，插件无法启动")
            await self.session.close()
            return
        
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())
        logger.info("[PymChat] 插件已启动，开始轮询公共聊天室")
    
    async def on_unload(self):
        """插件卸载：停止轮询，关闭连接"""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        if self.session:
            await self.session.close()
        logger.info("[PymChat] 插件已卸载")
    
    # ---------- 控制指令 ----------
    @filter.command("pymchat")
    async def command_status(self, event: AstrMessageEvent):
        """查看 PymChat 插件状态"""
        args = event.get_args()
        if args and args[0] == "reload":
            self.api_key = None
            if await self._login():
                yield event.plain_result("✅ PymChat 重新登录成功")
            else:
                yield event.plain_result("❌ PymChat 重新登录失败，请检查用户名密码")
            return
        
        status = "✅ 运行中" if self._running else "⏹️ 已停止"
        yield event.plain_result(
            f"PymChat 插件状态\n"
            f"- 轮询: {status}\n"
            f"- 最后消息ID: {self._last_msg_id}\n"
            f"- 已处理消息数: {len(self._processed_ids)}\n"
            f"- 当前人设: {self.persona[:50]}..."
        )
    
    # ---------- 内部方法 ----------
    async def _login(self) -> bool:
        """登录并获取 API Key"""
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
    
    async def _poll_messages(self):
        """轮询新消息"""
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
        """获取新消息"""
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
        """调用 LLM 生成回复并发送（支持自定义人设）"""
        try:
            provider_id = await self.context.get_current_chat_provider_id()
            if not provider_id:
                logger.warning("[PymChat] 未找到可用的聊天模型 ID，请检查模型配置")
                return
            
            # 构建带人设的提示词
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
                logger.warning("[PymChat] LLM 返回了未知格式")
                return
            
            if reply_text:
                await self._send_message(chatroom_id, reply_text)
                logger.info(f"[PymChat] 已回复 {sender_name}: {reply_text[:50]}")
            else:
                logger.warning("[PymChat] LLM 返回空内容")
        except Exception as e:
            logger.error(f"[PymChat] LLM 生成回复失败: {e}")
    
    async def _send_message(self, chatroom_id: str, content: str):
        """发送消息到聊天室"""
        if not self.api_key:
            logger.error("[PymChat] 无 API Key，无法发送")
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