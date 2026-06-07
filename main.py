from astrbot.api.star import Star, Context, register

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
        # 关键：导入适配器模块，触发 @register_platform_adapter 装饰器自动注册
        from .adapter.pymchat_adapter import PymChatAdapter  # noqa: F401

    async def on_load(self):
        pass

    async def on_unload(self):
        pass