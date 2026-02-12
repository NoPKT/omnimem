# Quickstart (10 minutes)

Language: [English](quickstart-10min.md) | [简体中文](quickstart-10min.zh-CN.md)

## New device

After npm publish:

```bash
npx -y omnimem
```

Without npm publish yet:

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## Open UI

```bash
~/.omnimem/bin/omnimem --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`.

## New project

```bash
~/.omnimem/app/scripts/attach_project.sh /path/to/project my-project-id
```

## Remove

```bash
~/.omnimem/bin/omnimem uninstall --yes
```
