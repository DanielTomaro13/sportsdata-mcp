"""`python -m sportsdata_mcp` → cli.main()."""

# Absolute import (not `from .cli`): this file is also PyInstaller's frozen entry script,
# where it runs as top-level `__main__` with no parent package — a relative import there
# fails with "attempted relative import with no known parent package". Absolute works both
# under `python -m sportsdata_mcp` and frozen.
from sportsdata_mcp.cli import main

if __name__ == "__main__":
    main()
