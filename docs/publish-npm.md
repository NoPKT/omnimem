# npm Publish Guide

Language: [English](publish-npm.md) | [简体中文](publish-npm.zh-CN.md)

This guide is for maintainers.

## 1) Prepare

```bash
npm run release:gate
npm run release:prepare
```

Apply version/changelog changes:

```bash
bash scripts/release_prepare.sh --apply
```

Optional partial gate:

```bash
bash scripts/release_gate.sh --skip-doctor --project-id OM --home ./.omnimem_gate
# Optional (faster local run): add --skip-docs if docs checks were already run.
```

Optional pack dry-run (recommended):

```bash
NPM_CONFIG_CACHE=./.npm-cache npm pack --dry-run
```

## 2) Publish

1. Ensure real repository URLs in `package.json`.
2. Login: `npm login`
3. Publish: `npm publish --access public`

## 3) Post-publish Verify

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

Optional global install check:

```bash
npm i -g omnimem
omnimem start
```

## 4) Rollback / Mitigation

If a bad version is published:

- prefer `npm deprecate` with clear guidance instead of immediate unpublish
- publish a fixed patch version quickly

Example deprecate command:

```bash
npm deprecate omnimem@<bad_version> "Broken release, please use >= <fixed_version>"
```

Note: `npm unpublish` has strict time/policy limits and may break consumers. Use only when truly necessary.
