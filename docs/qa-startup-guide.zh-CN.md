# Startup Guide 验收清单

English: [qa-startup-guide.md](qa-startup-guide.md)

用于验证新用户首次启动流程是否按预期工作。

## 可执行检查清单

1. 准备环境
   - 使用全新 `OMNIMEM_HOME`
   - 确保 `sync.github.remote_url` 为空
   - 在交互式终端运行（非 CI）

2. 路径 A：前置齐全自动运行
   - 前置：OAuth client id 可用，provider CLI 已安装并登录
   - 执行：`omnimem start`
   - 期望：startup guide 自动运行，不再额外确认

3. 路径 B：缺 client id
   - 前置：env/config 都没有 client id
   - 执行：`omnimem start`
   - 期望：只询问一次 client id，随后自动继续

4. 路径 C：provider 已安装但未登录
   - 前置：provider CLI 存在但未认证
   - 执行：`omnimem start`
   - 期望：提示登录命令，完成后继续流程

5. 路径 D：provider CLI 缺失
   - 前置：推荐 provider CLI 未安装
   - 执行：`omnimem start`
   - 期望：给出安装提示和 wizard 回退，不崩溃

6. broker_url 自动写回
   - 部署输出包含 URL 时，应自动写入 `sync.github.oauth.broker_url`
   - 若 URL 识别失败，启动应继续并给出手动补写命令

7. 关闭行为验证
   - 在启动提示输入 `never`
   - 再次运行 `omnimem start`
   - 期望：不再提示 startup guide（`setup.startup_guide_disabled=true`）

## 失败分流处理表

| 现象 | 常见原因 | 处理动作 |
|---|---|---|
| `startup guide 未触发` | 已禁用或非交互终端 | 检查 `setup.startup_guide_disabled`；确认在交互终端运行 |
| `provider CLI not found` | provider 工具未安装 | 按提示安装 `wrangler`/`vercel`/`railway`/`flyctl` 后重试 |
| `provider 未认证` | CLI 已装但未登录 | 先执行 provider 登录命令，再重跑 `omnimem start` |
| `部署成功但 URL 未写回` | URL 解析失败 | 手动写入 `sync.github.oauth.broker_url` |
| `OAuth 一直 pending` | 浏览器设备流未完成 | 先完成 verification URI，再继续轮询/确认 |
| `启动流程中断` | 运行时或工具链异常 | 先跑 `omnimem doctor`，再跑 `omnimem oauth-broker doctor` |

## 快速验证命令

```bash
omnimem doctor
omnimem oauth-broker doctor
```
