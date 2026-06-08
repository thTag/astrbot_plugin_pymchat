import json
import re
from typing import Dict, Any, Optional

import aiohttp

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Star, Context
from astrbot.api import logger

class PymChatSimplePlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.api_key: str = config.get("api_key", "")
        self.username: str = config.get("username", "")
        self.password: str = config.get("password", "")
        self.debug: bool = config.get("debug_mode", False)
        
        # 如果提供了用户名密码但没有 api_key，尝试自动登录
        if self.username and self.password and not self.api_key:
            # 注意：不能在 __init__ 中使用 async，改为在插件首次使用时触发
            self._need_auto_login = True
        else:
            self._need_auto_login = False
    
    async def _ensure_api_key(self) -> bool:
        """确保 api_key 有效，如果配置了用户名密码则尝试自动登录"""
        if self.api_key:
            return True
        if self._need_auto_login and self.username and self.password:
            return await self._auto_login()
        return False
    
    async def _auto_login(self) -> bool:
        """使用用户名密码登录并获取 API 密钥"""
        url = "https://chat.qplm.xyz/api/login.php"
        payload = {"username": self.username, "password": self.password}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if data.get("status") == 200:
                        api_key = data.get("data", {}).get("api_key", "")
                        if api_key:
                            self.api_key = api_key
                            self._need_auto_login = False
                            # 持久化保存 api_key 到配置
                            await self.context.save_config({"api_key": api_key})
                            logger.info(f"自动登录成功，API密钥已获取（有效期30天）")
                            return True
                        else:
                            logger.error("登录成功但未返回API密钥")
                            return False
                    else:
                        logger.error(f"登录失败: {data.get('message', '未知错误')}")
                        return False
        except Exception as e:
            logger.error(f"自动登录异常: {e}")
            return False
    
    async def _call_api(self, endpoint: str, method: str = "GET", 
                        params: Optional[Dict] = None,
                        data: Optional[Dict] = None,
                        json_data: Optional[Dict] = None) -> Dict:
        """
        异步调用 PymChat API 的通用方法
        :param endpoint: API 路径，如 "/api/ac.php"
        :param method: "GET" 或 "POST"
        :param params: URL 查询参数
        :param data: POST 表单数据
        :param json_data: POST JSON 数据
        """
        base_url = "https://chat.qplm.xyz"
        url = base_url + endpoint
        
        if params is None:
            params = {}
        # 自动添加 api_key（登录接口除外）
        if endpoint != "/api/login.php" and self.api_key:
            params["api_key"] = self.api_key
        
        if self.debug:
            logger.debug(f"API调用: {method} {url} params={params}")
        
        try:
            async with aiohttp.ClientSession() as session:
                if method.upper() == "GET":
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        result = await resp.json()
                elif method.upper() == "POST":
                    if json_data:
                        async with session.post(url, params=params, json=json_data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            result = await resp.json()
                    else:
                        async with session.post(url, params=params, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            result = await resp.json()
                else:
                    raise ValueError(f"不支持的HTTP方法: {method}")
                
                if self.debug:
                    logger.debug(f"API响应: {result}")
                return result
        except aiohttp.ClientError as e:
            logger.error(f"API请求失败: {e}")
            return {"status": 500, "message": str(e)}
        except json.JSONDecodeError:
            logger.error(f"响应不是有效的JSON")
            return {"status": 500, "message": "响应解析失败"}
    
    # ---------- 辅助方法：解析消息中的命令参数 ----------
    def _extract_command_content(self, event: AstrMessageEvent, prefix: str) -> str:
        """从消息中提取命令后面的内容"""
        full_text = event.message_str
        # 去除命令前缀（忽略大小写）
        pattern = re.compile(rf'^{re.escape(prefix)}\s+(.*)$', re.IGNORECASE)
        match = pattern.match(full_text.strip())
        if match:
            return match.group(1).strip()
        return ""
    
    def _extract_two_args(self, event: AstrMessageEvent, prefix: str):
        """提取命令后的两个参数，例如 send_private <user_id> <content>"""
        full_text = event.message_str
        pattern = re.compile(rf'^{re.escape(prefix)}\s+(\S+)\s+(.*)$', re.IGNORECASE)
        match = pattern.match(full_text.strip())
        if match:
            return match.group(1), match.group(2).strip()
        return None, None
    
    # ---------- 命令实现 ----------
    @filter.command("pymchat")
    async def pymchat_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """📚 PymChat 简易助手 v1.0 (异步版)

可用命令：
- pymchat help                : 显示本帮助
- pymchat send <消息>         : 发送公共消息
- pymchat get [数量]          : 获取公共消息（默认10条）
- pymchat send_private <用户ID> <消息> : 发送私信
- pymchat get_private [数量]  : 获取私信
- pymchat friends             : 查看好友列表
- pymchat add_friend <用户ID> : 添加好友
- pymchat status              : 查看插件状态
- pymchat login <用户名> <密码> : 手动登录获取API密钥

注意：消息内容如含空格无需引号，直接输入即可。"""
        yield event.plain_result(help_text)
    
    @filter.command("pymchat send")
    async def pymchat_send(self, event: AstrMessageEvent):
        """发送公共消息"""
        content = self._extract_command_content(event, "pymchat send")
        if not content:
            yield event.plain_result("❌ 用法：pymchat send <消息内容>")
            return
        
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API 密钥，请先使用 `pymchat login <用户名> <密码>` 登录或填写配置。")
            return
        
        result = await self._call_api("/api/ac.php", method="GET", params={
            "action": "send_message",
            "content": content
        })
        
        if result.get("status") == 200:
            yield event.plain_result(f"✅ 已发送消息到 PymChat 公共聊天室：{content}")
        else:
            yield event.plain_result(f"❌ 发送失败：{result.get('message', '未知错误')}")
    
    @filter.command("pymchat get")
    async def pymchat_get(self, event: AstrMessageEvent):
        """获取公共消息，可选参数 limit"""
        full_text = event.message_str.strip()
        limit = 10
        # 解析 pymchat get [数字]
        parts = full_text.split()
        if len(parts) >= 3 and parts[2].isdigit():
            limit = int(parts[2])
            if limit > 100:
                limit = 100
        
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API 密钥")
            return
        
        result = await self._call_api("/api/ac.php", method="GET", params={
            "action": "get_messages",
            "type": "public",
            "limit": limit
        })
        
        if result.get("status") == 200:
            messages = result.get("data", {}).get("messages", [])
            if not messages:
                yield event.plain_result("📭 暂无公共消息")
            else:
                msg_lines = []
                for m in messages[:10]:
                    sender = m.get("sdn", m.get("sn", "未知"))
                    content = m.get("content", "")
                    msg_lines.append(f"【{sender}】: {content}")
                result_text = "📨 最近消息：\n" + "\n".join(msg_lines)
                if len(messages) > 10:
                    result_text += f"\n... 共 {len(messages)} 条，仅显示前10条"
                yield event.plain_result(result_text)
        else:
            yield event.plain_result(f"❌ 获取失败：{result.get('message', '未知错误')}")
    
    @filter.command("pymchat send_private")
    async def pymchat_send_private(self, event: AstrMessageEvent):
        """发送私信：pymchat send_private <用户ID> <消息>"""
        user_id, content = self._extract_two_args(event, "pymchat send_private")
        if not user_id or not content:
            yield event.plain_result("❌ 用法：pymchat send_private <用户ID> <消息内容>")
            return
        
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API 密钥")
            return
        
        result = await self._call_api("/api/ac.php", method="GET", params={
            "action": "send_message",
            "recipient_id": user_id,
            "content": content
        })
        
        if result.get("status") == 200:
            yield event.plain_result(f"✅ 已发送私信给用户 {user_id}：{content}")
        else:
            yield event.plain_result(f"❌ 发送私信失败：{result.get('message', '未知错误')}")
    
    @filter.command("pymchat get_private")
    async def pymchat_get_private(self, event: AstrMessageEvent):
        """获取私信"""
        full_text = event.message_str.strip()
        limit = 10
        parts = full_text.split()
        if len(parts) >= 3 and parts[2].isdigit():
            limit = int(parts[2])
            if limit > 100:
                limit = 100
        
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API 密钥")
            return
        
        result = await self._call_api("/api/ac.php", method="GET", params={
            "action": "get_messages",
            "type": "private",
            "limit": limit
        })
        
        if result.get("status") == 200:
            messages = result.get("data", {}).get("messages", [])
            if not messages:
                yield event.plain_result("📭 暂无私信")
            else:
                msg_lines = []
                for m in messages[:10]:
                    sender = m.get("sdn", m.get("sn", "未知"))
                    content = m.get("content", "")
                    msg_lines.append(f"【{sender}】: {content}")
                result_text = "📨 最近私信：\n" + "\n".join(msg_lines)
                if len(messages) > 10:
                    result_text += f"\n... 共 {len(messages)} 条，仅显示前10条"
                yield event.plain_result(result_text)
        else:
            yield event.plain_result(f"❌ 获取私信失败：{result.get('message', '未知错误')}")
    
    @filter.command("pymchat friends")
    async def pymchat_friends(self, event: AstrMessageEvent):
        """获取好友列表"""
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API 密钥")
            return
        
        result = await self._call_api("/api/ac.php", method="GET", params={
            "action": "get_friends"
        })
        
        if result.get("status") == 200:
            friends = result.get("data", {}).get("friends", [])
            if not friends:
                yield event.plain_result("👥 暂无好友")
            else:
                lines = ["👥 好友列表："]
                for f in friends:
                    name = f.get("display_name", f.get("username", "未知"))
                    uid = f.get("id", "")
                    lines.append(f"- {name} (ID: {uid})")
                yield event.plain_result("\n".join(lines))
        else:
            yield event.plain_result(f"❌ 获取好友列表失败：{result.get('message', '未知错误')}")
    
    @filter.command("pymchat add_friend")
    async def pymchat_add_friend(self, event: AstrMessageEvent):
        """添加好友：pymchat add_friend <用户ID>"""
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("❌ 用法：pymchat add_friend <用户ID>")
            return
        
        user_id = parts[2]
        if not user_id.isdigit():
            yield event.plain_result("❌ 用户ID应为数字")
            return
        
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API 密钥")
            return
        
        result = await self._call_api("/api/ac.php", method="GET", params={
            "action": "send_friend_request",
            "recipient_id": user_id
        })
        
        if result.get("status") == 200:
            yield event.plain_result(f"✅ 已发送好友申请给用户 {user_id}")
        else:
            yield event.plain_result(f"❌ 发送好友申请失败：{result.get('message', '未知错误')}")
    
    @filter.command("pymchat status")
    async def pymchat_status(self, event: AstrMessageEvent):
        """查看插件状态"""
        status_lines = [
            "📊 PymChat 简易助手状态",
            f"🔑 API 密钥: {'已配置 ✅' if self.api_key else '未配置 ❌'}",
            f"🐛 调试模式: {'开启' if self.debug else '关闭'}",
            f"👤 用户名: {self.username or '未设置'}",
            "",
            "💡 提示: 使用 `pymchat help` 查看所有命令"
        ]
        yield event.plain_result("\n".join(status_lines))
    
    @filter.command("pymchat login")
    async def pymchat_login(self, event: AstrMessageEvent, username: str, password: str):
        """手动登录：pymchat login <用户名> <密码>"""
        url = "https://chat.qplm.xyz/api/login.php"
        payload = {"username": username, "password": password}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if data.get("status") == 200:
                        api_key = data.get("data", {}).get("api_key", "")
                        if api_key:
                            self.api_key = api_key
                            self.username = username
                            self.password = password
                            self._need_auto_login = False
                            # 持久化保存到配置
                            await self.context.save_config({
                                "api_key": api_key,
                                "username": username,
                                "password": password
                            })
                            display_name = data.get("data", {}).get("display_name", username)
                            yield event.plain_result(f"✅ 登录成功！\n用户：{display_name}\nAPI密钥已获取（有效期30天）")
                        else:
                            yield event.plain_result("⚠️ 登录成功但未返回API密钥")
                    else:
                        yield event.plain_result(f"❌ 登录失败：{data.get('message', '未知错误')}")
        except Exception as e:
            logger.error(f"登录异常: {e}")
            yield event.plain_result(f"❌ 登录异常：{str(e)}")


def register():
    """AstrBot 插件注册入口"""
    return PymChatSimplePlugin