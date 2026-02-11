# npm Publish Guide

## Pre-check

```bash
npm run release:gate
```

If needed, you can run a partial gate:

```bash
bash scripts/release_gate.sh --skip-doctor --project-id OM --home ./.omnimem_gate
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
