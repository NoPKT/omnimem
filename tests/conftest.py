from __future__ import annotations

import sys
from pathlib import Path


def _force_local_omnimem_import() -> None:
    # Some dev environments have a globally installed `omnimem` (e.g. via npm) that can
    # accidentally win import resolution under pytest. Force the repo root onto sys.path
    # and evict any already-imported global package so tests exercise the working tree.
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))

    mod = sys.modules.get("omnimem")
    mod_file = str(getattr(mod, "__file__", "") or "")
    if mod_file and str(root) not in mod_file:
        for name in list(sys.modules.keys()):
            if name == "omnimem" or name.startswith("omnimem."):
                sys.modules.pop(name, None)


_force_local_omnimem_import()

