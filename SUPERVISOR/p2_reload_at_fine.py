#!/usr/bin/env python3
"""One-shot safe-point reload of the running P2 driver (2026-11-25).

The P2 process that is meshing Medium was started before the Fine wall-limit fix in p2_fasttrack.py.
This helper waits until that process logs the start of its first Fine attempt (Medium is then published),
terminates that P2 process tree and its Fluent session, and exits; the orchestrator immediately resumes P2
with the updated code (Coarse and Medium are skipped as published). It never touches a P2 process started
after this helper, gives up after 4 h, and exits early if P2 fails/finishes on its own.
"""
import datetime as dt
import time
from pathlib import Path

import psutil

WS = Path(r"D:\FEA Coursework\Workspace")
P2LOG = WS / "logs" / "p2_fasttrack.log"
OUT = WS / "logs" / "p2_reload_at_fine.log"
T0 = time.time()


def note(msg):
    with OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def new_lines(offset):
    data = P2LOG.read_bytes()
    return data[offset:].decode("utf-8", errors="replace"), len(data)


def old_p2():
    out = []
    for p in psutil.process_iter(["cmdline", "create_time"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "p2_fasttrack.py" in cmd and (p.info.get("create_time") or T0) < T0:
            out.append(p)
    return out


def main():
    offset = P2LOG.stat().st_size if P2LOG.is_file() else 0
    note(f"armed; watching {P2LOG} from byte {offset}")
    while time.time() - T0 < 4 * 3600:
        time.sleep(20)
        text, offset = new_lines(offset)
        if "P2 FAILED" in text or "fine: PUBLISHED" in text:
            note("P2 ended on its own before a Fine attempt started; nothing to do")
            return 0
        if "fine: attempt" in text:
            procs = old_p2()
            if not procs:
                note("Fine attempt started but no pre-fix P2 process found; nothing to do")
                return 0
            victims = set()
            for p in procs:
                victims.add(p)
                try:
                    victims.update(p.children(recursive=True))
                except psutil.Error:
                    pass
            for p in psutil.process_iter(["exe"]):
                if str(p.info.get("exe") or "").lower().startswith(r"d:\ansys"):
                    victims.add(p)
            for p in victims:
                try:
                    p.kill()
                except psutil.Error:
                    pass
            note(f"Fine attempt started -> killed pre-fix P2 tree ({len(victims)} processes); orchestrator resumes P2")
            return 0
    note("timeout (4 h) without a Fine attempt; exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
