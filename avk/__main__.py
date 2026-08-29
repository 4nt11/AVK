# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point: `python -m avk <ingest|triage|oracle|scaffold> --project ...`."""
from .run import main

if __name__ == "__main__":
    main()
