# Common Commands

Language: [English](common-commands.md) | [简体中文](common-commands.zh-CN.md)

## Start and Stop

```bash
~/.omnimem/bin/omnimem start
omnimem stop
```

## Agent Entry

```bash
omnimem codex
omnimem claude
```

## Diagnostics

```bash
omnimem doctor
omnimem oauth-broker doctor
```

## Sync and Lifecycle

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
bash scripts/attach_project.sh /path/to/project my-project-id
bash scripts/detach_project.sh /path/to/project
~/.omnimem/bin/omnimem uninstall --yes
```

