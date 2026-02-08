# npm Publish Guide

## Pre-check

```bash
npm_config_cache=/tmp/omnimem-npm-cache npm run pack:check
bash scripts/verify_phase_d.sh
```

## Publish

1. Set real repository URLs in `package.json`.
2. `npm login`
3. `npm publish --access public`

## User command after publish

```bash
npx -y omnimem
```

Optional:

```bash
npx -y omnimem --host 127.0.0.1 --port 8765
```
