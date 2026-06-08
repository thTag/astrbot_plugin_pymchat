"""
PymChat 适配器 for AstrBot
使用 curl 调用 PymChat API
"""
import json
import re
import subprocess
import asyncio
from typing import Dict, Any, Optional, List

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Star, Context
from astrbot.api import logger


class PymChatPlugin(Star):
    """PymChat 适配器 - 使用 curl 调用 API"""

    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.api_key: str = config.get("api_key", "")
        self.username: str = config.get("username", "")
        self.password: str = config.get("password", "")
        self.debug: bool = config.get("debug_mode", False)
        self.base_url: str = "https://chat.qplm.xyz"

        # 启动时自动尝试获取 API Key
        if self.username and self.password and not self.api_key:
            asyncio.create_task(self._auto_login_on_start())

    async def _auto_login_on_start(self):
        """插件初始化时自动登录获取 API Key"""
        logger.info("检测到未配置 API Key，正在尝试自动登录...")
        success = await self._auto_login()
        if success:
            logger.info("自动登录成功，API Key 已获取")
        else:
            logger.warning("自动登录失败，请检查用户名密码配置")

    async def _auto_login(self) -> bool:
        """自动登录获取 API Key"""
        url = f"{self.base_url}/api/login.php"
        payload = json.dumps({"username": self.username, "password": self.password})

        cmd = [
            "curl", "-s", "-X", "POST",
            url,
            "-H", "Content-Type: application/json",
            "-d", payload
        ]

        try:
            result = await self._run_curl(cmd)
            if result.get("status") == 200:
                api_key = result.get("data", {}).get("api_key", "")
                if api_key:
                    self.api_key = api_key
                    await self.context.save_config({"api_key": api_key})
                    return True
            logger.error(f"自动登录失败: {result.get('message', '未知错误')}")
            return False
        except Exception as e:
            logger.error(f"自动登录异常: {e}")
            return False

    async def _run_curl(self, cmd: List[str]) -> Dict[str, Any]:
        """执行 curl 命令并解析 JSON 响应"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            response = stdout.decode('utf-8').strip()

            if self.debug:
                logger.debug(f"执行命令: {' '.join(cmd)}")
                logger.debug(f"响应: {response}")

            if not response:
                return {"status": 500, "message": "空响应"}

            return json.loads(response)
        except json.JSONDecodeError:
            logger.error(f"JSON 解析失败: {response}")
            return {"status": 500, "message": "响应解析失败"}
        except Exception as e:
            logger.error(f"curl 执行异常: {e}")
            return {"status": 500, "message": str(e)}

    async def _call_pymchat_api(self, action: str, **kwargs) -> Dict[str, Any]:
        """调用 PymChat API (使用 curl)"""
        if not self.api_key:
            return {"status": 401, "message": "未配置 API Key"}

        params = {"api_key": self.api_key, "action": action}
        params.update(kwargs)

        # 构建 URL 参数
        query_parts = [f"api_key={self.api_key}", f"action={action}"]
        for k, v in kwargs.items():
            query_parts.append(f"{k}={v}")

        # URL 编码处理
        encoded_params = []
        for part in query_parts:
            if "=" in part:
                key, val = part.split("=", 1)
                from urllib.parse import quote
                encoded_params.append(f"{key}={quote(val, safe='')}")

        url = f"{self.base_url}/api/ac.php?" + "&".join(encoded_params)

        # 记录 curl 命令（用于调试展示给用户）
        curl_cmd = f'curl "{url}"'
        logger.debug(f"执行: {curl_cmd}")

        cmd = ["curl", "-s", url]

        try:
            result = await self._run_curl(cmd)
            result["_curl_cmd"] = curl_cmd  # 附加调试信息
            return result
        except Exception as e:
            return {"status": 500, "message": str(e), "_curl_cmd": curl_cmd}

    async def _ensure_api_key(self) -> bool:
        """确保 API Key 可用，必要时自动登录"""
        if self.api_key:
            return True
        if self.username and self.password:
            return await self._auto_login()
        return False

    def _parse_command(self, event: AstrMessageEvent, prefix: str) -> tuple:
        """解析命令，返回 (action, content)"""
        full_text = event.message_str.strip()
        pattern = re.compile(rf'^{re.escape(prefix)}\s+(.*)$', re.IGNORECASE)
        match = pattern.match(full_text)
        if match:
            content = match.group(1).strip()
            parts = content.split(maxsplit=1)
            if len(parts) >= 2:
                return parts[0], parts[1]
            return parts[0] if parts else ("", "")
        return "", ""

    @filter.command("pymchat")
    async def pymchat_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """📚 PymChat 助手 v2.0 (curl 版)

用法: pymchat <操作> [参数]

操作列表:
  help              显示本帮助
  send <消息>       发送公共消息
  get [数量]        获取公共消息（默认10条）
  send_private <用户ID> <消息>  发送私信
  get_private [数量] 获取私信（默认10条）
  friends           查看好友列表
  add_friend <用户ID>  添加好友
  status            查看插件状态

示例:
  pymchat send 你好世界
  pymchat get 20
  pymchat send_private 123 你好呀
  pymchat add_friend 456"""
        yield event.plain_result(help_text)

    @filter.command("pymchat send")
    async def pymchat_send(self, event: AstrMessageEvent):
        """发送公共消息"""
        content = event.message_str.replace("/pymchat send", "").strip()
        if not content:
            yield event.plain_result("❌ 用法: pymchat send <消息内容>")
            return

        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API Key，请先在插件配置中设置 username/password 或 api_key")
            return

        result = await self._call_pymchat_api("send_message", content=content)

        if result.get("status") == 200:
            # 显示实际执行的 curl 命令（调试信息）
            curl_cmd = result.get("_curl_cmd", "")
            yield event.plain_result(
                f"✅ 已发送消息到 PymChat 公共聊天室\n"
                f"📨 内容: {content}\n"
                f"🔧 curl: {curl_cmd}"
            )
        else:
            yield event.plain_result(f"❌ 发送失败: {result.get('message', '未知错误')}")

    @filter.command("pymchat get")
    async def pymchat_get(self, event: AstrMessageEvent):
        """获取公共消息"""
        full_text = event.message_str.strip()
        limit = 10

        # 解析数量参数
        parts = full_text.split()
        if len(parts) >= 3 and parts[2].isdigit():
            limit = min(int(parts[2]), 100)

        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API Key")
            return

        result = await self._call_pymchat_api("get_messages", type="public", limit=limit)

        if result.get("status") == 200:
            messages = result.get("data", {}).get("messages", [])
            if not messages:
                yield event.plain_result("📭 暂无公共消息")
            else:
                lines = [f"📨 公共消息 (共 {len(messages)} 条):\n"]
                for m in messages[:10]:
                    sender = m.get("sdn", m.get("sn", "未知"))
                    content = m.get("content", "")
                    time = m.get("time", "")
                    lines.append(f"【{sender}】{time}: {content}")

                output = "\n".join(lines)
                if len(messages) > 10:
                    output += f"\n... 仅显示前 10 条"
                yield event.plain_result(output)
        else:
            yield event.plain_result(f"❌ 获取失败: {result.get('message', '未知错误')}")

    @filter.command("pymchat send_private")
    async def pymchat_send_private(self, event: AstrMessageEvent):
        """发送私信"""
        content = event.message_str.replace("/pymchat send_private", "").strip()
        parts = content.split(maxsplit=1)

        if len(parts) < 2:
            yield event.plain_result("❌ 用法: pymchat send_private <用户ID> <消息>")
            return

        user_id, message = parts[0], parts[1]

        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API Key")
            return

        result = await self._call_pymchat_api(
            "send_message",
            recipient_id=user_id,
            content=message
        )

        if result.get("status") == 200:
            yield event.plain_result(
                f"✅ 已发送私信给用户 {user_id}\n"
                f"📨 内容: {message}\n"
                f"🔧 curl: {result.get('_curl_cmd', '')}"
            )
        else:
            yield event.plain_result(f"❌ 发送失败: {result.get('message', '未知错误')}")

    @filter.command("pymchat get_private")
    async def pymchat_get_private(self, event: AstrMessageEvent):
        """获取私信"""
        full_text = event.message_str.strip()
        limit = 10

        parts = full_text.split()
        if len(parts) >= 3 and parts[2].isdigit():
            limit = min(int(parts[2]), 100)

        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API Key")
            return

        result = await self._call_pymchat_api("get_messages", type="private", limit=limit)

        if result.get("status") == 200:
            messages = result.get("data", {}).get("messages", [])
            if not messages:
                yield event.plain_result("📭 暂无私信")
            else:
                lines = [f"📨 私信 (共 {len(messages)} 条):\n"]
                for m in messages[:10]:
                    sender = m.get("sdn", m.get("sn", "未知"))
                    content = m.get("content", "")
                    lines.append(f"【{sender}】: {content}")

                output = "\n".join(lines)
                if len(messages) > 10:
                    output += f"\n... 仅显示前 10 条"
                yield event.plain_result(output)
        else:
            yield event.plain_result(f"❌ 获取失败: {result.get('message', '未知错误')}")

    @filter.command("pymchat friends")
    async def pymchat_friends(self, event: AstrMessageEvent):
        """查看好友列表"""
        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API Key")
            return

        result = await self._call_pymchat_api("get_friends")

        if result.get("status") == 200:
            friends = result.get("data", {}).get("friends", [])
            if not friends:
                yield event.plain_result("👥 暂无好友")
            else:
                lines = [f"👥 好友列表 ({len(friends)} 人):\n"]
                for f in friends:
                    name = f.get("display_name", f.get("username", "未知"))
                    uid = f.get("id", "")
                    lines.append(f"• {name} (ID: {uid})")
                yield event.plain_result("\n".join(lines))
        else:
            yield event.plain_result(f"❌ 获取失败: {result.get('message', '未知错误')}")

    @filter.command("pymchat add_friend")
    async def pymchat_add_friend(self, event: AstrMessageEvent):
        """添加好友"""
        full_text = event.message_str.replace("/pymchat add_friend", "").strip()

        if not full_text or not full_text.isdigit():
            yield event.plain_result("❌ 用法: pymchat add_friend <用户ID>")
            return

        if not await self._ensure_api_key():
            yield event.plain_result("❌ 未配置 API Key")
            return

        result = await self._call_pymchat_api("send_friend_request", recipient_id=full_text)

        if result.get("status") == 200:
            yield event.plain_result(f"✅ 已发送好友申请给用户 {full_text}")
        else:
            yield event.plain_result(f"❌ 添加失败: {result.get('message', '未知错误')}")

    @filter.command("pymchat status")
    async def pymchat_status(self, event: AstrMessageEvent):
        """查看插件状态"""
        status_lines = [
            "📊 PymChat 助手状态",
            f"🔑 API Key: {'已配置 ✅' if self.api_key else '未配置 ❌'}",
            f"👤 用户名: {self.username or '未设置'}",
            f"🐛 调试模式: {'开启' if self.debug else '关闭'}",
            f"🌐 API 地址: {self.base_url}",
            "",
            "💡 使用 `pymchat help` 查看所有命令"
        ]
        yield event.plain_result("\n".join(status_lines))

    async def terminate(self):
        """插件卸载时调用"""
        logger.info("PymChat 插件已卸载")


def register():
    """AstrBot 插件注册入口"""
    return PymChatPlugin