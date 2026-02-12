# Documentation Index

Language: [English](README.md) | [简体中文](README.zh-CN.md)

## User Path

- quickstart: `quickstart-10min.md`
- common commands: `common-commands.md`
- install/attach/uninstall: `install-uninstall.md`
- WebUI configuration: `webui-config.md`
- GitHub OAuth broker (optional): `oauth-broker.md`

## Maintainer Path

- npm publish: `publish-npm.md`
- startup guide QA: `qa-startup-guide.md`
- advanced ops / eval / tuning: `advanced-ops.md`

## Local Docs Checks

```bash
python3 scripts/check_docs_i18n.py
python3 scripts/report_docs_health.py --out eval/docs_health_report.json
python3 scripts/report_webui_i18n_coverage.py --out eval/webui_i18n_report.json
```

## Architecture and Specs

- architecture overview: `architecture.md`
- integration spec: `integration-spec.md`
- sync and adapters: `sync-and-adapters.md`
- phase workflow log: `phase-workflow.md`
