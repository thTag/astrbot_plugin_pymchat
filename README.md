## PymChat 聊天室插件 for AstrBot

<p align="center">
  <img src="logo.png" alt="PymChat Plugin Logo" width="120">
</p>

将 [PymChat](https://chat.pymstu.top) 接入 [AstrBot](https://astrbot.app) ，通过全功能 API 实现公共聊天室、私聊、好友系统和群聊的全面交互。

---

### ✨ 功能

#### 🌐 公共聊天室
- 自动轮询公共消息，实时响应聊天室互动
- 支持 `@机器人` 或自定义关键词触发 AI 回复
- 自动获取账号昵称，无需手动配置机器人名称

#### 💬 好友与私聊
- 发送/接收私信（需互为好友）
- 查看好友列表、发送/同意/拒绝好友申请、删除好友

#### 👥 群聊功能
- 获取群消息、发送群消息
- 查询我的群聊列表

#### 🎮 命令系统
- **`/pymchat`** – 查看插件运行状态
- **`/pymchat_reload`** – 重载配置并重新初始化
- **`/pymchat_sync`** – 同步昵称到插件
- **`/pymchat_debug on/off`** – 动态开关调试日志

---

### 🚀 快速开始

#### 1. 安装插件

- **AstrBot WebUI 一键安装**：在"插件管理"中搜索 `pymchat`，点击安装即可。
- **手动安装**：将仓库克隆到 `addons` 目录，重启 AstrBot。

```bash
cd /path/to/astrbot/addons
git clone https://github.com/thTag/astrbot_plugin_pymchat
```

#### 2. 配置插件

在 AstrBot WebUI 的"插件配置"页面填写以下信息（`_conf_schema.json` 已自动生成配置表单）：

| 配置项 | 说明 | 必填 |
|--------|------|------|
| `username` | PymChat 用户名 | 必填（若未提供 API Key） |
| `password` | PymChat 密码 | 必填（若未提供 API Key） |
| `api_key` | API 密钥 | 选填 |
| `trigger_keywords` | 触发关键词，英文逗号分隔 | 选填，默认 `bot` |
| `system_prompt` | AI 人设 | 选填 |
| `poll_interval` | 轮询间隔（秒） | 选填，默认 `3` |
| `debug_mode` | 开启详细日志 | 选填，默认 `false` |

**配置加载机制**：AstrBot 在载入插件时会检测插件目录下的 `_conf_schema.json`，自动解析配置并保存在 `data/config/<plugin_name>_config.json` 下，并在实例化插件类时将配置以 `AstrBotConfig` 对象形式传递给插件的 `__init__` 方法，无需手动读取本地文件，请优先在 WebUI 中填写配置。

#### 3. 使用

在 PymChat 公共聊天室中发送：

```
@机器人昵称 你好
```

或触发关键词（如 `th`）：

```
th 你好
```

机器人将调用 AstrBot 配置的 LLM 生成回复并发送到聊天室。

---

### 📖 详细命令列表

| 命令 | 说明 | 示例 |
|------|------|------|
| `/pymchat` | 查看插件状态 | `/pymchat` |
| `/pymchat_reload` | 重载配置并重新初始化 | `/pymchat_reload` |
| `/pymchat_sync` | 同步昵称 | `/pymchat_sync` |
| `/pymchat_send` | 手动发送公共消息 | `/pymchat_send 大家好` |
| `/pymchat_send_private <用户ID> <消息>` | 发送私信 | `/pymchat_send_private user_xxx 你好` |
| `/pymchat_friends` | 查看好友列表 | `/pymchat_friends` |
| `/pymchat_add_friend <用户ID> [消息]` | 发送好友申请 | `/pymchat_add_friend user_xxx 加个好友` |
| `/pymchat_friend_requests` | 查看好友申请 | `/pymchat_friend_requests` |
| `/pymchat_accept_friend <申请ID>` | 同意好友申请 | `/pymchat_accept_friend req_xxx` |
| `/pymchat_delete_friend <好友ID>` | 删除好友 | `/pymchat_delete_friend user_xxx` |
| `/pymchat_group <群号> <消息>` | 发送群消息 | `/pymchat_group 123456 大家好` |
| `/pymchat_debug on/off` | 开关调试日志 | `/pymchat_debug on` |

---

### 🔧 前置要求

- AstrBot >= v4.20（`AstrBotConfig` 配置机制）
- Python >= 3.12
- 已配置的 LLM 供应商

---

### ❗ 常见问题

#### Q1：插件状态显示“已停止”
插件启动时会自动尝试登录 PymChat。若登录失败，状态会显示为“已停止”。请在 WebUI 中检查 `username` 和 `password` 是否正确，然后使用 `/pymchat_reload` 重试。

#### Q2：触发关键词无效
请确认 WebUI 中的 `trigger_keywords` 配置已正确保存。执行 `/pymchat` 查看当前关键词列表。支持英文逗号分隔多个关键词（如 `th,nova,ai`）。

#### Q3：私信发送失败
- 确认对方已是您的好友
- 检查 `recipient_id` 格式是否正确（如 `user_1767542930_6563`）

#### Q4：群聊功能无法使用
请在 WebUI 中将 `enable_group_chat` 设为 `true`，并重启插件。群聊 API 地址为独立域名 `https://chat.qplm.xyz/qunliao/api.php`。

---

### 📝 配置示例

```json
{
  "username": "your_username",
  "password": "your_password",
  "trigger_keywords": "th,ai,小助手",
  "system_prompt": "你是一个友好的AI助手。",
  "poll_interval": 5,
  "debug_mode": true
}
```

---

### 🔗 相关链接

- [PymChat API 文档](https://chat.qplm.xyz/api)
- [PymChat](https://chat.pymstu.top)

---

### 📄 许可证

[LICENSE](LICENSE)

---

<p align="center">
  Made with ❤️ thTag by th-dd
</p>
