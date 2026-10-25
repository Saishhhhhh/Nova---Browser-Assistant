#!/usr/bin/env python
"""Single entry point: `python run_jarvis.py`. See jarvis/app.py for what happens and the available flags
(`python run_jarvis.py --help`)."""
import sys

from jarvis.app import main

if __name__ == "__main__":
    sys.exit(main())
