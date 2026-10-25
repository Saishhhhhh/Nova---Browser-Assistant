#!/usr/bin/env python
"""Single entry point: `python run_mycroft.py`. See mycroft/app.py for what happens and the available flags
(`python run_mycroft.py --help`)."""
import sys

from mycroft.app import main

if __name__ == "__main__":
    sys.exit(main())
