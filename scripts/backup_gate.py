#!/usr/bin/env python3
"""Decide whether the nightly backup should run now (it is 9 PM US Eastern), for the schedule."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.backup import RUN_HOUR, RUN_TZ, should_run


def main() -> None:
    event = os.environ.get("EVENT_NAME", "")
    now = datetime.now(timezone.utc)
    if event != "schedule":
        run, why = True, f"started by {event or 'hand'}, so it runs now"
    elif should_run(now):
        run, why = True, f"it is {RUN_HOUR}:00 in {RUN_TZ}"
    else:
        run, why = False, f"not {RUN_HOUR}:00 in {RUN_TZ} (the other of the two daily schedules covers it)"
    print(f"[BACKUP] {'Running' if run else 'Skipping'}: {why}.")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")


if __name__ == "__main__":
    main()
