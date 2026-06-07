from astrbot.api.star import Star, Context, register
from astrbot.api import logger
from .adapter import PymChatAdapter

@register(
    "astrbot_plugin_pymchat",
    "叹点",
    "PymChat 平台适配器插件",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_pymchat"
)
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)

    async def on_load(self):
        # 手动注册适配器
        platform_manager = self.context.get_platform_manager()
        platform_manager.register_adapter("pymchat", PymChatAdapter)
        logger.info("[PymChat] 手动注册适配器成功")

    async def on_unload(self):
        logger.info("[PymChat] 插件卸载")