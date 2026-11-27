import os
import subprocess
import sys
import textwrap
import time

import pytest

from process_guard import contain

pytestmark = pytest.mark.skipif(os.name != "nt", reason="job objects are Windows-only")

SRC = os.path.join(os.path.dirname(__file__), os.pardir, "src")


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def test_guarded_child_dies_when_the_guard_closes():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    guard = contain(child)
    assert guard is not None
    guard.close()
    child.wait(5)


def test_guarded_child_dies_when_its_parent_is_killed():
    # The parent stands in for a backend that crashes or is force-closed mid-chapter.
    parent_code = textwrap.dedent(f"""
        import subprocess, sys, time
        sys.path.insert(0, {os.path.abspath(SRC)!r})
        from process_guard import contain
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        guard = contain(child)
        print(child.pid, flush=True)
        time.sleep(120)
    """)
    parent = subprocess.Popen([sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline())
    assert alive(child_pid)
    parent.kill()
    parent.wait(5)
    deadline = time.monotonic() + 5
    while alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not alive(child_pid)
