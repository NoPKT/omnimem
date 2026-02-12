# 常用命令参考

English: [common-commands.md](common-commands.md)

## 启动与停止

```bash
~/.omnimem/bin/omnimem start
omnimem stop
```

## Agent 模式命令

```bash
omnimem codex
omnimem claude
```

## 诊断

```bash
omnimem doctor
omnimem oauth-broker doctor
```

## 同步与生命周期

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
bash scripts/attach_project.sh /path/to/project my-project-id
bash scripts/detach_project.sh /path/to/project
~/.omnimem/bin/omnimem uninstall --yes
```
