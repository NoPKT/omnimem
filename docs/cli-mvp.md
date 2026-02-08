# CLI MVP

Command entry:

- Local repo: `./bin/omnimem`
- Installed: `~/.omnimem/bin/omnimem`

Examples:

```bash
./bin/omnimem write --summary "example" --body "text"
./bin/omnimem find example --limit 10
./bin/omnimem checkpoint --summary "phase checkpoint"
./bin/omnimem brief --project-id demo
./bin/omnimem verify
./bin/omnimem sync --mode github-status
./bin/omnimem sync --mode github-bootstrap
```
