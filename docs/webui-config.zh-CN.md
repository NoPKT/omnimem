# WebUI 与配置（中文）

> English: [webui-config.md](webui-config.md)

默认配置路径：

- `$OMNIMEM_HOME/omnimem.config.json`
- 回退：`~/.omnimem/omnimem.config.json`

启动：

```bash
~/.omnimem/bin/omnimem
```

## 安全默认值

- WebUI 默认只监听本地：`127.0.0.1`
- 非本地监听必须加 `--allow-non-localhost`
- 可选 token 鉴权：

```bash
OMNIMEM_WEBUI_TOKEN='your-token' ~/.omnimem/bin/omnimem start
# 或
~/.omnimem/bin/omnimem start --webui-token 'your-token'
```

启用 token 后，请求需带头：`X-OmniMem-Token: <token>`

## WebUI 提供能力

- 状态/动作、配置、记忆浏览
- daemon 开关与 bootstrap 同步
- GitHub 快速认证与仓库设置
- 纯 OAuth 设备流（无 `gh` CLI 也可）
- 可选 OAuth Broker（仅代理认证，不经过记忆数据）
- 路由模板、批量标签、回滚预览、治理解释
- 多语言切换（含更完整 static text 覆盖）
- 元素级 `title` 提示（本地化 tip）

## OAuth token 存储

- 默认存于：`<OMNIMEM_HOME>/runtime/github_oauth_token.json`
- `github-pull/github-push` 通过 `GIT_ASKPASS` 使用该 token 访问 `https://github.com/...`
- 不要提交 token 文件
