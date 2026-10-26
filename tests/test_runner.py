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


def test_crashed_scoring_is_marked_failed(tmp_path):
    store = Store(tmp_path / "eureka.db")
    run_id = store.start_run("fetch: Ana", "3 new releases")
    runner = RunManager(load_config(), store, command=lambda rid: [sys.executable, "-c", "import sys; sys.exit(3)"])

    runner.score(run_id)
    assert wait_until(lambda: not runner.is_running())
    run = store.run(run_id)
    assert run["status"] == "error"
    assert run["summary"] == "3 new releases · Scoring process exited with code 3"


def test_queued_runs_score_one_after_another(tmp_path):
    store = Store(tmp_path / "eureka.db")
    db = str(tmp_path / "eureka.db").replace("\\", "/")
    # Stand-in for `agent.py score`: finishes its run after a short pause.
    script = ("import sys, time; sys.path.insert(0, '.'); from pathlib import Path; from eureka.store import Store; "
              f"time.sleep(0.5); Store(Path('{db}')).finish_run(int(sys.argv[1]), 'ok', 'scored')")
    runner = RunManager(load_config(), store, command=lambda rid: [sys.executable, "-c", script, str(rid)])

    first, second = store.start_run("fetch: Ana"), store.start_run("fetch: Bo")
    runner.score(first)
    runner.score(second)
    assert store.run(second)["status"] == "running"  # waiting its turn
    assert wait_until(lambda: not runner.is_running())
    assert store.run(first)["status"] == "ok" and store.run(second)["status"] == "ok"
