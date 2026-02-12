# Quickstart (10 minutes)

Language: [English](quickstart-10min.md) | [简体中文](quickstart-10min.zh-CN.md)

## 1) Install

```bash
bash scripts/install.sh
```

## 2) Start OmniMem

```bash
~/.omnimem/bin/omnimem start
```

Open: `http://127.0.0.1:8765`

## 3) Configure GitHub sync (optional)

In WebUI:

- `Configuration` -> `GitHub Quick Setup`
- Click `Sign In via GitHub`
- Select/create repo and apply setup

Note: memory sync remains local Git operations on your machine.

## 4) Sync on a new device (optional)

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## 5) Attach a project (optional)

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

## 6) Daily commands

```bash
omnimem codex
omnimem claude
omnimem doctor
omnimem stop
```

## 7) Remove OmniMem

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

## Troubleshooting

- Port already in use:
  - `~/.omnimem/bin/omnimem --host 127.0.0.1 --port 8766`
- GitHub login issues:
  - run `omnimem doctor`
  - see `docs/oauth-broker.md` for OAuth broker shortcuts
