# 可选 GitHub OAuth Broker（中文）

> English: [oauth-broker.md](oauth-broker.md)

仅用于简化 GitHub 登录流程，不参与记忆数据同步链路。

## 为什么需要

- 无 broker：每台机器都要本地 `gh` 登录或手动准备 OAuth client id
- 有 broker：WebUI 可经统一端点发起/轮询设备流登录
- 同步仍在本地执行（`github-pull` / `github-push`）

## 快速开始（自动化）

```bash
# 初始化模板
omnimem oauth-broker init --provider cloudflare --dir ./oauth-broker-cloudflare --client-id Iv1.your_client_id

# 预览部署命令
omnimem oauth-broker deploy --provider cloudflare --dir ./oauth-broker-cloudflare

# 执行部署
omnimem oauth-broker deploy --provider cloudflare --dir ./oauth-broker-cloudflare --apply
```

向导模式：

```bash
omnimem oauth-broker wizard
```

自检：

```bash
omnimem oauth-broker doctor
```

自动流水线：

```bash
omnimem oauth-broker auto
omnimem oauth-broker auto --apply
```

## 启动自动引导联动

`omnimem start` / `omnimem webui` 在缺少 sync/auth 配置时会触发引导。

- 若已满足条件（provider 已登录 + client id 可用），可无提示自动执行
- 缺 client id 时可在启动流程内一次性补齐
- provider 未登录时可直接执行登录命令再继续
- 若部署输出中识别到 URL，可自动写入 `sync.github.oauth.broker_url`

可关闭引导：

- `--no-startup-guide`
- `OMNIMEM_STARTUP_GUIDE=0`

## 安全边界

- broker 只代理 OAuth 设备流
- broker 不读写 OmniMem 记忆数据
- broker 不长期保存 token
- token 仍由 OmniMem 本地 runtime 持久化
