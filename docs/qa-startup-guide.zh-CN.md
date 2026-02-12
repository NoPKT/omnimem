# Startup Guide 验收清单（中文）

> English: [qa-startup-guide.md](qa-startup-guide.md)

用于验证新用户首次启动体验。

## 1) 准备环境

- 使用全新 `OMNIMEM_HOME`
- 配置中 `sync.github.remote_url` 为空
- 在交互式终端中运行（非 CI）

## 2) 路径 A：前置齐全，自动运行

前置：OAuth client id 可用，provider CLI 已安装并登录

```bash
omnimem start
```

期望：startup guide 无需确认，自动执行引导与部署流程。

## 3) 路径 B：缺 client id

前置：env/config 中都无 client id

期望：启动时只询问一次 client id，随后继续自动流程。

## 4) 路径 C：provider 已安装但未登录

前置：CLI 可用但未认证

期望：提示登录命令，执行成功后继续自动流程。

## 5) 路径 D：provider 未安装

前置：推荐 provider CLI 不存在

期望：展示安装提示并提供 wizard 回退，不崩溃。

## 6) broker_url 自动写回

- 若部署输出包含 URL：应自动写入 `sync.github.oauth.broker_url`
- 若识别失败：启动不阻断，并给出手动补写命令

## 7) 永久关闭

在提示中输入 `never`，再次启动不再提示。
