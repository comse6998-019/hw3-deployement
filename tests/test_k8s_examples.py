import pathlib, shutil, subprocess, yaml, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
STATEFULSET = ROOT / "examples/k8s/statefulset.example.yaml"
JOB = ROOT / "examples/k8s/job-init.example.yaml"
def docs(path): return list(yaml.safe_load_all(path.read_text()))
def by_kind(path): return {d["kind"]: d for d in docs(path)}
def all_example_text(): return STATEFULSET.read_text() + JOB.read_text()


def test_examples_parse():
    assert sorted(by_kind(STATEFULSET)) == ["Service", "StatefulSet"]
    assert sorted(by_kind(JOB)) == ["Job"]

def test_examples_are_not_the_stack():
    text = all_example_text().lower()
    for word in ("postgres", "mcp", "agent", "pg_isready"):
        assert word not in text, word

def test_statefulset_has_headless_service_and_claim_template():
    kinds = by_kind(STATEFULSET)
    assert kinds["Service"]["metadata"]["name"] == "kv"
    assert kinds["Service"]["spec"]["clusterIP"] == "None"
    spec = kinds["StatefulSet"]["spec"]
    assert spec["serviceName"] == "kv"
    assert spec["replicas"] == 1
    assert spec["template"]["spec"]["containers"][0]["image"] == "redis:7.4-alpine"
    (claim,) = spec["volumeClaimTemplates"]
    assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert claim["spec"]["resources"]["requests"]["storage"] == "1Gi"

def test_job_has_init_container_and_restart_policy():
    job = by_kind(JOB)["Job"]
    assert job["metadata"]["name"] == "wait-then-run"
    assert job["spec"]["backoffLimit"] == 10
    pod = job["spec"]["template"]["spec"]
    assert pod["restartPolicy"] == "OnFailure"
    (init,) = pod["initContainers"]
    assert init["image"] == "busybox:1.37"
    assert "nc -z kv 6379" in " ".join(init["command"])

@pytest.mark.parametrize("path", [STATEFULSET, JOB], ids=lambda p: p.name)
def test_dry_run_client(path):
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl is not installed")
    run = subprocess.run(["kubectl", "apply", "--dry-run=client", "--validate=false", "-f", str(path)],
                         capture_output=True, text=True, timeout=60)
    if run.returncode != 0 and any(s in run.stderr for s in ("connection refused", "Unable to connect", "no route to host", "i/o timeout")):
        pytest.skip("kubectl needs an API server here: " + run.stderr.strip()[:200])
    assert run.returncode == 0, run.stderr
