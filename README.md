# PymChat 适配器 for AstrBot

将 PymChat 聊天平台封装为简单的命令式插件。支持发送/获取公共消息、私信、好友管理。

## 安装

1. 将本插件目录放入 `data/plugins/`
2. 重启 AstrBot 或通过 WebUI 重载插件
3. 在插件配置页面填写 `username`/`password` 或 `api_key`

## 命令

| 命令 | 说明 |
|------|------|
| `pymchat help` | 显示帮助 |
| `pymchat send 你好` | 发送公共消息 |
| `pymchat get 10` | 获取最近10条公共消息 |
| `pymchat send_private 123 你好` | 发送私信给用户ID 123 |
| `pymchat get_private 5` | 获取最近5条私信 |
| `pymchat friends` | 查看好友列表 |
| `pymchat add_friend 456` | 添加好友 |
| `pymchat status` | 查看插件状态 |
| `pymchat login 用户名 密码` | 手动登录获取API密钥 |

## 配置说明

- `api_key`: 手动填入API密钥（登录后获取）
- `username` + `password`: 自动登录获取密钥（二选一）
- `debug_mode`: 开启后打印详细请求日志