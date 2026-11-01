"""PyInstaller entry point: absolute import so freezing works."""
import sys

from mediarenamer.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
