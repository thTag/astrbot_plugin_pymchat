from astrbot.api.star import Star, Context, register
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent

from .adapter import PymChatAdapter

@register(
    "astrbot_plugin_pymchat",
    "YourName",
    "PymChat 平台适配器",
    "1.0.0",
    "https://github.com/YourName/astrbot_plugin_pymchat"
)
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)
        self.adapter = None

    async def on_load(self):
        try:
            platform_manager = self.context.get_platform_manager()
            platform_manager.register_adapter("pymchat", PymChatAdapter)
            logger.info("[PymChat] 适配器注册成功")
        except Exception as e:
            logger.error(f"[PymChat] 适配器注册失败: {e}")

    @filter.command("pc")
    async def control(self, event: AstrMessageEvent):
        yield event.plain_result("PymChat adapter is working.")