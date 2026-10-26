#!/usr/bin/env python
"""Single entry point: `python run_nova.py`. See nova/app.py for what happens and the available flags
(`python run_nova.py --help`)."""
import sys

from nova.app import main

if __name__ == "__main__":
    sys.exit(main())
