# 10 分钟快速上手（中文）

> English: [quickstart-10min.md](quickstart-10min.md)

## 1) 安装

```bash
bash scripts/install.sh
```

## 2) 启动

```bash
~/.omnimem/bin/omnimem
```

默认地址：`http://127.0.0.1:8765`

## 3) 新设备同步（可选）

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## 4) 项目接入（可选）

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
```

## 5) 基本命令

```bash
omnimem find --limit 8 "query"
omnimem write --layer short --kind note --summary "..." --body "..." --project-id OM
omnimem checkpoint --summary "..." --project-id OM
```

## 6) 发布前检查

```bash
npm run release:gate
```
