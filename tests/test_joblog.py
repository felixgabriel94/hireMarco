from hiremarco.joblog import JobLog, JobRow


def test_append_and_total(tmp_path):
    log = JobLog(tmp_path / "jobs.jsonl")
    log.append(JobRow(job="a", model="m", cost_usd=0.5, ts="2026-10-26T20:00:00-04:00"))
    log.append(JobRow(job="b", model="m", cost_usd=0.25, ts="2026-10-27T09:00:00-04:00"))
    assert len(log.rows()) == 2
    assert log.total_usd() == 0.75
    assert log.total_usd("2026-10-27") == 0.25


def test_missing_log_is_empty(tmp_path):
    log = JobLog(tmp_path / "none.jsonl")
    assert log.rows() == []
    assert log.total_usd() == 0.0
