import sys
import time

from eureka.config import load_config
from eureka.runner import RunManager
from eureka.store import Store


def wait_until(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_crashed_run_is_marked_failed(tmp_path):
    store = Store(tmp_path / "eureka.db")
    # Stand-in for `agent.py run` that registers a run and then dies without finishing it.
    db = str(tmp_path / "eureka.db").replace("\\", "/")
    script = (
        "import sys; sys.path.insert(0, '.'); from eureka.store import Store; from pathlib import Path; "
        f"Store(Path('{db}')).start_run('test'); sys.exit(3)"
    )
    runner = RunManager(load_config(), store, command=lambda trigger: [sys.executable, "-c", script])

    assert runner.start("manual: test")
    assert not runner.start("manual: again")  # one at a time
    assert wait_until(lambda: not runner.is_running())
    run = store.runs(1)[0]
    assert run["status"] == "error"
    assert "exited with code 3" in run["summary"]


def test_blocks_while_another_process_runs(tmp_path):
    store = Store(tmp_path / "eureka.db")
    store.start_run("cli")  # a run started elsewhere, still going
    runner = RunManager(load_config(), store, command=lambda trigger: [sys.executable, "-c", "pass"])
    assert runner.is_running()
    assert not runner.start("manual: test")
