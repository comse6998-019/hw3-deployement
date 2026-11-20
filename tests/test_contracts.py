import copy, json, pathlib, tomllib, jsonschema
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
