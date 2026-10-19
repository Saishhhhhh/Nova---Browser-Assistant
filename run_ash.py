#!/usr/bin/env python
"""Single entry point: `python run_ash.py`. See ash/app.py for what happens and the available flags
(`python run_ash.py --help`)."""
import sys

from ash.app import main

if __name__ == "__main__":
    sys.exit(main())
