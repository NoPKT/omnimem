# Install / Attach / Uninstall

## Install

```bash
bash scripts/install.sh
```

Wizard mode:

```bash
bash scripts/install.sh --wizard
```

Bootstrap on new device:

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## Start

```bash
~/.omnimem/bin/omnimem
```

## Attach project

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

## Uninstall

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

Uninstall + detach project files:

```bash
~/.omnimem/bin/omnimem uninstall --yes --detach-project /path/to/project
```
