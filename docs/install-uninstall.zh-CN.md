# 安装与卸载（中文）

> English: [install-uninstall.md](install-uninstall.md)

## 安装

```bash
bash scripts/install.sh
```

## 新设备引导

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## 项目接入

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

## 项目移除

```bash
bash scripts/detach_project.sh /path/to/project
```

## 卸载

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

说明：卸载会删除 OmniMem home 及相关本地运行文件；如需保留数据，请先备份。
