# npm 发布流程（中文）

> English: [publish-npm.md](publish-npm.md)

## 发布前

```bash
npm run release:gate
npm run release:prepare
```

可选只跑部分 gate：

```bash
bash scripts/release_gate.sh --skip-doctor --project-id OM --home ./.omnimem_gate
```

## 打包验证

```bash
NPM_CONFIG_CACHE=./.npm-cache npm pack --dry-run
```

若出现 `~/.npm` 权限问题（EPERM），继续使用上面的本地缓存方式。

## 发布后验证

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

或：

```bash
npm i -g omnimem
omnimem start
```
