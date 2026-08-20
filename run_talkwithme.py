"""PyInstaller entry point. Lives outside the talkwithme package so that
`talkwithme/__main__.py`'s relative imports (`from . import ...`) resolve
correctly — running a file *inside* a package as the top-level script
makes Python treat it as a parentless module and relative imports fail.
"""
import sys

from talkwithme.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
