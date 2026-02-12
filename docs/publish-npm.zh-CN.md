# npm 发布流程

English: [publish-npm.md](publish-npm.md)

本页面向维护者。

## 1) 发布前准备

```bash
npm run release:gate
npm run release:prepare
```

应用版本与 changelog 变更：

```bash
bash scripts/release_prepare.sh --apply
```

可选（仅跑部分 gate）：

```bash
bash scripts/release_gate.sh --skip-doctor --project-id OM --home ./.omnimem_gate
# 可选（本地更快）：如果已单独执行文档检查，可附加 --skip-docs。
```

可选（推荐）打包预检：

```bash
NPM_CONFIG_CACHE=./.npm-cache npm pack --dry-run
```

## 2) 执行发布

1. 确认 `package.json` 中仓库 URL 为真实地址
2. 登录：`npm login`
3. 发布：`npm publish --access public`

## 3) 发布后验证

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

可选全局安装验证：

```bash
npm i -g omnimem
omnimem start
```

## 4) 回滚与止损

若发布了错误版本：

- 优先使用 `npm deprecate` 给出升级指引，而不是立刻 unpublish
- 尽快发布修复版本（patch）

示例：

```bash
npm deprecate omnimem@<bad_version> "该版本有缺陷，请升级到 >= <fixed_version>"
```

说明：`npm unpublish` 有时间窗口和策略限制，且可能破坏下游依赖，除非必要不建议使用。
