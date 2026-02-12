# 安装、接入与卸载

English: [install-uninstall.md](install-uninstall.md)

本页用于生命周期操作。  
首次使用请优先看 `docs/quickstart-10min.zh-CN.md`。

## 安装 OmniMem

```bash
bash scripts/install.sh
```

可选引导安装：

```bash
bash scripts/install.sh --wizard
```

## 启动

```bash
~/.omnimem/bin/omnimem start
```

## 新设备同步

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## 项目接入文件

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

仅移除项目接入文件：

```bash
bash scripts/detach_project.sh /path/to/project
```

## 卸载 OmniMem

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

一条命令卸载并移除指定项目接入：

```bash
~/.omnimem/bin/omnimem uninstall --yes --detach-project /path/to/project
```

## 卸载前保留数据（可选）

如需保留本地状态，请先备份 `~/.omnimem` 后再卸载。

## 常见问题

- 安装后提示找不到 `omnimem`：
  - 先用全路径 `~/.omnimem/bin/omnimem`
- 启动失败：
  - 运行 `omnimem doctor`
- GitHub 同步认证异常：
  - 查看 `docs/oauth-broker.zh-CN.md`
