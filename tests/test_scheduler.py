"""Scheduler orchestration: cycle isolation, stop checks, report shape.

Pure/fake — no network, no DB. The DB path is covered by the live suite
(test_live_db.py) which runs on the plane against real Postgres.
"""

from substrate.scheduler import CycleReport, TenantCycleReport, run_forever


def test_cycle_report_shape():
    report = CycleReport(tenants=2, errors=1)
    report.per_tenant["a"] = {"error": None}
    report.per_tenant["b"] = {"error": "boom"}
    data = report.as_dict()
    assert data["tenants"] == 2 and data["errors"] == 1
    assert set(data["per_tenant"]) == {"a", "b"}


def test_tenant_cycle_report_defaults_are_honest():
    report = TenantCycleReport(tenant="acme")
    # A defaulted report claims NOTHING happened — honest zero, not guessed.
    data = report.as_dict()
    assert data["error"] is None
    assert data["postings_written"] == 0
    assert data["delivery_unconfigured"] == 0  # honest zero, not guessed


def test_run_forever_stops_between_cycles():
    # Contract: stop() is polled before each cycle and between sleep slices; a
    # True verdict ends the loop without finishing the interval.
    cycles: list[CycleReport] = []
    stop_polls = {"n": 0}

    def stop() -> bool:
        stop_polls["n"] += 1
        return stop_polls["n"] > 1  # poll 1 runs the cycle, poll 2 stops

    sleeps: list[float] = []

    def cycle() -> CycleReport:
        cycles.append(CycleReport(tenants=1))
        return cycles[-1]

    run_forever(
        cycle,
        interval_seconds=10,
        stop=stop,
        sleep=lambda s: sleeps.append(s),
        log=lambda msg: None,
    )
    assert len(cycles) == 1  # exactly one cycle ran
    assert sleeps == []  # stop fired right after the cycle: no sleep happened


def test_run_forever_survives_cycle_exception():
    # A failing cycle must not kill the loop — isolation IS the contract.
    calls = {"n": 0}

    def cycle() -> CycleReport:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return CycleReport(tenants=0)

    polls = {"n": 0}

    def stop() -> bool:
        polls["n"] += 1
        return calls["n"] >= 2  # stop once the second cycle has run

    run_forever(
        cycle,
        interval_seconds=1,
        stop=stop,
        sleep=lambda s: None,
        log=lambda msg: None,
    )
    assert calls["n"] == 2


def test_sleep_slices_honor_stop_mid_interval():
    # Slices are bounded (≤5s) so a stop signal is honored mid-interval.
    stop_flag = {"value": False}
    sleeps: list[float] = []

    def cycle() -> CycleReport:
        return CycleReport(tenants=0)

    def stop() -> bool:
        return stop_flag["value"]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        stop_flag["value"] = True  # flip mid-sleep sequence

    run_forever(
        cycle,
        interval_seconds=30,
        stop=stop,
        sleep=sleep,
        log=lambda msg: None,
    )
    assert len(sleeps) >= 1
    assert max(sleeps) <= 5.0


def test_logging_failure_falls_back_and_loop_survives():
    # Gate round-14: a broken log file killed the loop from the SUCCESS path
    # (log() ran after the try/except), and the error handler re-raised it
    # through the same broken logger. Logging failures must fall back to
    # stderr and never stop subsequent cycles.
    cycles: list[CycleReport] = []
    failing_log = {"calls": 0}

    def broken_log(msg: str) -> None:
        failing_log["calls"] += 1
        raise OSError("log file unwritable")

    calls = {"n": 0}

    def cycle() -> CycleReport:
        calls["n"] += 1
        report = CycleReport(tenants=1)
        if calls["n"] > 1:
            report.errors = -1  # sentinel the current impl doesn't produce; harmless
        cycles.append(report)
        return report

    polls = {"n": 0}

    def stop() -> bool:
        polls["n"] += 1
        return calls["n"] >= 2  # two cycles, both logged through the broken logger

    run_forever(
        cycle,
        interval_seconds=1,
        stop=stop,
        sleep=lambda s: None,
        log=broken_log,
    )
    assert calls["n"] == 2  # loop survived both logging failures
    assert failing_log["calls"] == 2
