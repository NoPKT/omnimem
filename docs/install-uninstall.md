# Install, Attach, Uninstall

Language: [English](install-uninstall.md) | [简体中文](install-uninstall.zh-CN.md)

Use this page for lifecycle operations.  
For first-time setup flow, use `docs/quickstart-10min.md`.

## Install OmniMem

```bash
bash scripts/install.sh
```

Optional guided installer:

```bash
bash scripts/install.sh --wizard
```

## Start

```bash
~/.omnimem/bin/omnimem start
```

## Bootstrap on a new device

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## Attach project files

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

Detach project files only:

```bash
bash scripts/detach_project.sh /path/to/project
```

## Uninstall OmniMem

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

Uninstall and detach one project in one command:

```bash
~/.omnimem/bin/omnimem uninstall --yes --detach-project /path/to/project
```

## Keep data before uninstall (optional)

Before uninstalling, backup `~/.omnimem` if you want to restore local state later.

## Troubleshooting

- `omnimem` command not found after install:
  - use full path `~/.omnimem/bin/omnimem`
- startup fails:
  - run `omnimem doctor`
- GitHub sync auth issues:
  - check `docs/oauth-broker.md`
