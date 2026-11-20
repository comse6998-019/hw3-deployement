import copy, json, pathlib, tomllib, jsonschema, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
def schema(name): return json.loads((ROOT / f"{name}.schema.json").read_text())
def validator(name): return jsonschema.Draft202012Validator(schema(name), format_checker=jsonschema.FormatChecker())
def load_config(): return tomllib.loads((ROOT / "examples/config.example.toml").read_text())
def load_report(): return json.loads((ROOT / "examples/report.example.json").read_text())
def unique_alert_ids(report):
    ids = [row["alert_id"] for row in report["alerts"]]
    return len(ids) == len(set(ids))
def errors_without(key):
    bad = {k: v for k, v in load_config().items() if k != key}
    return list(validator("config").iter_errors(bad))


def test_config_example_validates(): validator("config").validate(load_config())

def test_config_needs_each_table():
    for key in ("scan", "model", "budget", "run", "checkpoint", "postgres", "mcp"):
        assert errors_without(key), key

def test_config_rejects_key_value_in_api_key_var():
    cfg = load_config(); cfg["model"]["api_key_var"] = "sk-abc123"
    assert list(validator("config").iter_errors(cfg))

def test_config_rejects_value_in_password_var():
    cfg = load_config(); cfg["postgres"]["password_var"] = "hunter2"
    assert list(validator("config").iter_errors(cfg))

def test_config_rejects_other_provider_and_durability():
    cfg = load_config(); cfg["model"]["provider"] = "anthropic"
    assert list(validator("config").iter_errors(cfg))
    cfg = load_config(); cfg["checkpoint"]["durability"] = "async"
    assert list(validator("config").iter_errors(cfg))

def test_config_rejects_bad_url_run_id_and_port():
    for table, key, value in (("model", "base_url", "ftp://x"), ("mcp", "url", "mcp:8000"),
                              ("run", "id", "run 1"), ("postgres", "port", 70000)):
        cfg = load_config(); cfg[table][key] = value
        assert list(validator("config").iter_errors(cfg)), (table, key)

def test_scan_blocks_match_enum():
    blocks = sorted((ROOT / "briefs/scan").glob("*.toml"))
    assert len(blocks) == 3
    for path in blocks:
        cfg = load_config(); cfg["scan"] = tomllib.loads(path.read_text())["scan"]
        validator("config").validate(cfg)

def test_config_rejects_changed_scan_block():
    cfg = load_config(); cfg["scan"] = copy.deepcopy(cfg["scan"]); cfg["scan"]["max_alerts"] = 501
    assert list(validator("config").iter_errors(cfg))


def test_report_example_validates(): validator("report").validate(load_report())

def test_report_needs_run_id():
    rep = load_report(); del rep["run_id"]
    assert list(validator("report").iter_errors(rep))

def test_report_example_alert_ids_unique(): assert unique_alert_ids(load_report())

def test_duplicate_alert_id_detected():
    rep = load_report(); rep["alerts"][1] = copy.deepcopy(rep["alerts"][0])
    assert unique_alert_ids(rep) is False


def trace_events():
    return [json.loads(l) for l in (ROOT / "examples/trace.example.jsonl").read_text().splitlines()]
def ledger_rows():
    return [json.loads(l) for l in (ROOT / "examples/ledger.example.jsonl").read_text().splitlines()]
def open_rows(ledger):
    done = {r["call_id"] for r in ledger if r["status"] == "call_finished"}
    return [r for r in ledger if r["status"] == "call_started" and r["call_id"] not in done]
def finished_tokens(ledger):
    return sum(r["usage"]["input"] + r["usage"]["output"] for r in ledger if r["status"] == "call_finished")

def attempt_of(events):
    # The attempt of each event: the attempt of the last resume at or before it.
    out, cur = [], None
    for e in events:
        cur = e["attempt"] if e["kind"] == "resume" else cur
        out.append(cur)
    return out

def check_trace(events, report=None):
    report = report or load_report()
    assert [e["step"] for e in events] == list(range(1, len(events) + 1)), "steps"
    assert events[0]["kind"] == "resume" and events[0]["attempt"] == 1, "first event"
    attempts = [e["attempt"] for e in events if e["kind"] == "resume"]
    assert attempts == list(range(1, len(attempts) + 1)), "attempts"
    assert [e["kind"] for e in events].count("terminal") == 1 and events[-1]["kind"] == "terminal", "terminal"
    calls = [e["usage"] for e in events if e["kind"] == "model_call"]
    total = events[-1]["usage_total"]
    assert total == {k: sum(u.get(k, 0) for u in calls) for k in set(total).union(*calls)}, "usage"
    found = [a for a, e in zip(attempt_of(events), events) if e["kind"] == "discovery"]
    assert len(found) == len(set(found)), "one discovery per attempt"
    for i, e in enumerate(events):
        if e["kind"] == "tool_request":
            # A kill during a tool call ends the attempt, so a resume can come next.
            nxt = events[i + 1]
            assert nxt["kind"] == "resume" or (nxt["kind"] == "tool_result" and nxt["tool"] == e["tool"]), e["step"]
    for row in report["alerts"]:
        mine = [e for e in events if e["alert_id"] == row["alert_id"] and e["kind"] == "state_change"]
        final = [e for e in mine if "alert_status" in e]
        assert final, row["alert_id"]
        # Earlier finalizing events are repeats. Only the last one must match the row.
        assert (final[-1]["alert_status"], final[-1]["label"]) == (row["status"], row["label"]), row["alert_id"]
        fixes = [e for e in mine if "alert_status" not in e]
        assert fixes and fixes[-1]["checks"] == row["remediation"]["checks"], row["alert_id"]

def check_ledger(rows, events):
    started, finished = {}, {}
    for i, r in enumerate(rows):
        seen = started if r["status"] == "call_started" else finished
        assert r["call_id"] not in seen, ("two rows", r["status"], r["call_id"])
        seen[r["call_id"]] = i
    for cid, i in finished.items():
        assert cid in started and started[cid] < i, ("finished before started", cid)
        assert rows[started[cid]]["attempt"] == rows[i]["attempt"], ("attempt", cid)
    by_id = {r["call_id"]: r for r in rows}
    for a, e in zip(attempt_of(events), events):
        if e["kind"] == "model_call":
            assert by_id[e["call_id"]]["attempt"] == a, ("trace attempt", e["call_id"])

def test_trace_lines_validate():
    for e in trace_events(): validator("trace").validate(e)

def test_resume_event_needs_fields():
    event = next(e for e in trace_events() if e["kind"] == "resume")
    for key in ("attempt", "checkpoint_id", "next_alert_id"):
        bad = {k: v for k, v in event.items() if k != key}
        assert list(validator("trace").iter_errors(bad)), key
    for key, value in (("attempt", 0), ("checkpoint_id", 5), ("next_alert_id", "a b")):
        assert list(validator("trace").iter_errors({**event, key: value})), key

def test_refused_by_kernel_rejected():
    result = {"step": 1, "ts": 1796119200.0, "run_id": "run-001", "alert_id": None,
              "kind": "tool_result", "tool": "read_file", "ok": False, "error": "refused", "refused_by": "kernel"}
    assert list(validator("trace").iter_errors(result))
    assert not list(validator("trace").iter_errors({**result, "refused_by": "server"}))

def test_via_codeact_rejected():
    request = {"step": 1, "ts": 1796119200.0, "run_id": "run-001", "alert_id": None,
               "kind": "tool_request", "tool": "locate", "args": {}, "via": "codeact"}
    assert list(validator("trace").iter_errors(request))

def test_trace_example_meets_cross_line_rules(): check_trace(trace_events())

def test_two_resumes_before_terminal_pass():
    check_trace(trace_events())
    assert [e["attempt"] for e in trace_events() if e["kind"] == "resume"] == [1, 2]

def test_cross_line_rules_catch_breaks():
    ev = trace_events()
    gap = copy.deepcopy(ev); gap[3]["step"] = 99
    no_end = copy.deepcopy(ev)[:-1]
    skip = copy.deepcopy(ev); [e for e in skip if e["kind"] == "resume"][1]["attempt"] = 3
    wrong = copy.deepcopy(ev); wrong[-1]["usage_total"]["input"] += 1
    status = copy.deepcopy(ev)
    next(e for e in status if e.get("alert_status") == "error")["alert_status"] = "classified"
    for bad in (gap, no_end, skip, wrong, status):
        with pytest.raises(AssertionError): check_trace(bad)

def renumber(events):
    return [{**e, "step": n} for n, e in enumerate(events, 1)]

def test_only_last_finalizing_event_must_match_row():
    ev = trace_events()
    i, first = next((i, e) for i, e in enumerate(ev) if e.get("alert_status") == "classified")
    check_trace(renumber(ev[:i] + [{**first, "label": 0}] + ev[i:]))
    with pytest.raises(AssertionError): check_trace(renumber(ev[:-1] + [{**first, "label": 0}, ev[-1]]))

def test_kill_during_tool_call_resume_follows_request():
    ev = trace_events()
    i = next(i for i, e in enumerate(ev) if e["kind"] == "tool_request")
    assert ev[i + 2]["kind"] == "resume"
    check_trace(renumber(ev[:i + 1] + ev[i + 2:]))

def test_tool_request_followed_by_other_event_fails():
    ev = trace_events()
    i = next(i for i, e in enumerate(ev) if e["kind"] == "tool_request")
    call = next(e for e in ev if e["kind"] == "model_call")
    bad = renumber(ev[:i + 1] + [{**call, "usage": {"input": 0, "output": 0}}] + ev[i + 2:])
    with pytest.raises(AssertionError): check_trace(bad)

def test_one_discovery_per_attempt():
    ev = trace_events()
    assert [e["kind"] for e in ev].count("discovery") == 2
    i = next(i for i, e in enumerate(ev) if e["kind"] == "discovery")
    with pytest.raises(AssertionError): check_trace(renumber(ev[:i + 1] + [ev[i]] + ev[i + 1:]))

def test_ledger_lines_validate():
    for r in ledger_rows(): validator("ledger").validate(r)

def test_finished_row_needs_usage():
    row = next(r for r in ledger_rows() if r["status"] == "call_finished")
    assert list(validator("ledger").iter_errors({k: v for k, v in row.items() if k != "usage"}))
    started = next(r for r in ledger_rows() if r["status"] == "call_started")
    assert list(validator("ledger").iter_errors({**started, "usage": row["usage"]}))

def test_ledger_timestamps_go_up():
    stamps = [r["ts"] for r in ledger_rows()]
    assert stamps == sorted(stamps)

def test_open_row_not_charged():
    led = ledger_rows(); assert any(open_rows(led))
    assert finished_tokens(led) == load_report()["budget"]["used_tokens"]

def test_ledger_trace_report_share_run_id():
    ids = {r["run_id"] for r in ledger_rows()} | {e["run_id"] for e in trace_events()}
    assert ids == {load_report()["run_id"]}

def test_finished_rows_pair_with_model_calls():
    done = {r["call_id"]: r["usage"] for r in ledger_rows() if r["status"] == "call_finished"}
    calls = [e for e in trace_events() if e["kind"] == "model_call"]
    assert sorted(e["call_id"] for e in calls) == sorted(done)
    assert all(done[e["call_id"]] == e["usage"] for e in calls)
    assert not {r["call_id"] for r in open_rows(ledger_rows())} & set(done)

def test_ledger_example_meets_cross_line_rules(): check_ledger(ledger_rows(), trace_events())

def test_ledger_rules_catch_breaks():
    led, ev = ledger_rows(), trace_events()
    first_done = next(i for i, r in enumerate(led) if r["status"] == "call_finished")
    two_starts = led + [copy.deepcopy(led[0])]
    two_ends = led + [copy.deepcopy(led[first_done])]
    early = [led[first_done]] + [r for i, r in enumerate(led) if i != first_done]
    orphan = [r for i, r in enumerate(led) if i != first_done - 1]
    attempt = copy.deepcopy(led)
    for r in attempt:
        if r["call_id"] == "call-0003": r["attempt"] = 1
    for bad in (two_starts, two_ends, early, orphan, attempt):
        with pytest.raises(AssertionError): check_ledger(bad, ev)
