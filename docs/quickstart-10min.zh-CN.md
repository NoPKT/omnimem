# 10 分钟快速上手

English: [quickstart-10min.md](quickstart-10min.md)

## 1) 安装

```bash
bash scripts/install.sh
```

## 2) 启动 OmniMem

```bash
~/.omnimem/bin/omnimem start
```

打开：`http://127.0.0.1:8765`

## 3) 配置 GitHub 同步（可选）

在 WebUI 中：

- 进入 `Configuration` -> `GitHub Quick Setup`
- 点击 `Sign In via GitHub`
- 选择/创建仓库并应用配置

说明：记忆同步仍是你本机的 Git 操作，不经过记忆中转服务。

## 4) 新设备同步（可选）

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## 5) 接入项目（可选）

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

## 6) 日常命令

见：`docs/common-commands.zh-CN.md`

## 7) 卸载 OmniMem

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

## 常见排障

- 端口被占用：
  - `~/.omnimem/bin/omnimem --host 127.0.0.1 --port 8766`
- GitHub 登录异常：
  - 先运行 `omnimem doctor`
  - 再看 `docs/oauth-broker.zh-CN.md` 的 OAuth broker 快捷部署方案
