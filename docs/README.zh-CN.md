# 文档索引

English: [README.md](README.md)

## 用户路径

- 快速上手：`quickstart-10min.zh-CN.md`
- 常用命令：`common-commands.zh-CN.md`
- 安装/接入/卸载：`install-uninstall.zh-CN.md`
- WebUI 配置：`webui-config.zh-CN.md`
- GitHub OAuth Broker（可选）：`oauth-broker.zh-CN.md`

## 维护者路径

- npm 发布：`publish-npm.zh-CN.md`
- 启动引导 QA：`qa-startup-guide.zh-CN.md`
- 高级运维/评测/调参：`advanced-ops.zh-CN.md`

## 本地文档检查

```bash
python3 scripts/check_docs_i18n.py
python3 scripts/report_docs_health.py --out eval/docs_health_report.json
python3 scripts/report_webui_i18n_coverage.py --out eval/webui_i18n_report.json
```

## 架构与规范

- 架构总览：`architecture.md`
- 集成规范：`integration-spec.md`
- 同步与适配：`sync-and-adapters.md`
- 分阶段流程日志：`phase-workflow.md`
