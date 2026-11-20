import json, os, pathlib, random, subprocess, sys, tempfile, tomllib
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
# name: (clone source, env var for a local clone, pinned commit). A local clone in the env var avoids the network clone.
TARGETS = {
    "owasp-benchmark-python": ("https://github.com/OWASP-Benchmark/BenchmarkPython", "OWASP_CHECKOUT", "f1291485808b66e20ddb6b01b10dc71b3df8c8ba"),
    "radicale": ("https://github.com/Kozea/Radicale", "RADICALE_CHECKOUT", "eff8027f3dc4910be1659ee71f4b4a454ade5a8c"),
    "sglang": ("https://github.com/sgl-project/sglang", "SGLANG_CHECKOUT", "bbe9c7eeb520b0a67e92d133dfc137a3688dc7f2"),
}
SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

def cap_alerts(results, limit=500):
    # Keep the first `limit` alerts: HIGH before MEDIUM, then path, line (integer), and test_id. The order is total, so the list is fixed.
    key = lambda r: (SEVERITY_RANK[r["issue_severity"]], pathlib.PurePath(r["filename"]).as_posix(), int(r["line_number"]), r["test_id"])
    return sorted(results, key=key)[:limit]

def bandit(checkout, block):
    # Bandit scans a directory with -r and a file as given. Globs expand here, as the shell would.
    paths = sorted(str(p.relative_to(checkout)) for pat in block["paths"] for p in (checkout.glob(pat) if "*" in pat else [checkout / pat]))
    exclude = ["-x", ",".join(block["exclude"])] if block["exclude"] else []
    r = subprocess.run([sys.executable, "-m", "bandit", "-q", "-f", "json", "-ll", "-r", *exclude, *paths],
                       cwd=checkout, capture_output=True, text=True)
    # Bandit exits 0 (clean) or 1 (alerts) and always writes JSON to stdout. Anything else means bandit did not run.
    assert r.stdout.lstrip().startswith("{"), f"bandit did not run (exit {r.returncode}).\n{r.stderr}"
    return json.loads(r.stdout)["results"]

@pytest.mark.parametrize("target", TARGETS)
def test_count_matches(target):
    src, env, pin = TARGETS[target]
    block = tomllib.loads((ROOT / f"briefs/scan/{target}.toml").read_text())["scan"]
    counts = json.loads((ROOT / "briefs/scan/counts.json").read_text())
    with tempfile.TemporaryDirectory() as d:
        co = pathlib.Path(d) / target
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", os.environ.get(env, src), str(co)], check=True)
        subprocess.run(["git", "-C", str(co), "checkout", "-q", pin], check=True)
        assert len(cap_alerts(bandit(co, block), block["max_alerts"])) == counts[target]

def test_cap_order():
    rows = [{"issue_severity": "HIGH" if i % 3 == 0 else "MEDIUM", "filename": f"./pkg/m{i % 7}.py", "line_number": i % 50, "test_id": f"B{100 + i % 5}"}
            for i in range(600)]
    capped = cap_alerts(rows)
    assert len(capped) == 500
    severities = [r["issue_severity"] for r in capped]
    assert severities == sorted(severities, key=SEVERITY_RANK.get)
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    assert cap_alerts(shuffled) == capped
