import sys
from omnimem.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--version":
        from omnimem import __version__
        print(f"omnimem {__version__}")
        sys.exit(0)
    sys.exit(main())
