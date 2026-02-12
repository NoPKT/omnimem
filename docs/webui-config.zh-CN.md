# WebUI 与配置

English: [webui-config.md](webui-config.md)

## 推荐默认（建议先这样用）

多数用户只需要：

```bash
~/.omnimem/bin/omnimem start
```

然后打开：

- `http://127.0.0.1:8765`

默认配置路径：

- `$OMNIMEM_HOME/omnimem.config.json`
- 回退：`~/.omnimem/omnimem.config.json`

## GitHub 同步配置（推荐走 WebUI）

在 WebUI 的 `Configuration` 页：

- `GitHub Quick Setup`
- `Sign In via GitHub`
- 选择/创建仓库
- `Apply GitHub Setup`

这条路径下，记忆同步仍是你本机 Git 操作。

## 进阶选项（按需开启）

### WebUI token 鉴权

```bash
OMNIMEM_WEBUI_TOKEN='your-token' ~/.omnimem/bin/omnimem start
# 或
~/.omnimem/bin/omnimem start --webui-token 'your-token'
```

启用后，API 请求必须携带：`X-OmniMem-Token: <token>`。

### 非本地监听

仅在明确理解网络暴露风险时使用：

```bash
~/.omnimem/bin/omnimem start --host 0.0.0.0 --allow-non-localhost --webui-token 'your-token'
```

### 守护进程重试参数

```bash
~/.omnimem/bin/omnimem start \
  --daemon-retry-max-attempts 4 \
  --daemon-retry-initial-backoff 1 \
  --daemon-retry-max-backoff 8
```

### OAuth broker（可选）

仅用于简化 OAuth 登录体验（例如用户机器上没有本地 CLI 认证环境）。

- 文档：`docs/oauth-broker.zh-CN.md`
- broker 只代理 OAuth 设备流 start/poll，不承载记忆数据

## 风险与安全提示

- 默认保持 WebUI 仅本地监听。
- 若开启非本地监听（`--allow-non-localhost`），必须同时启用 token。
- token 文件路径：`<OMNIMEM_HOME>/runtime/github_oauth_token.json`。
- 不要提交 token/runtime 文件。
- 启动与认证诊断命令：

```bash
omnimem doctor
```

## 功能地图（参考）

WebUI 提供：

- 状态/动作/配置/记忆页面
- daemon 指标、健康检查、冲突恢复提示
- 治理/维护预览流程
- layer board、路由模板、批量标签
- 多语言文案与本地化 tooltip

详细 API 与能力说明见：

- `docs/advanced-ops.zh-CN.md`
- `spec/daemon-state.schema.json`
