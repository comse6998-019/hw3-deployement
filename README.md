# hw3-deployement

COMS E6998-019 HW3: take your HW2 MCP agent and deploy it on Kubernetes. The
agent keeps its state in Postgres, resumes after a kill, and scans one of three
full targets. The assignment is in [briefs/hw3.pdf](briefs/hw3.pdf) (source:
`briefs/hw3.tex`).

There is no starter code. You design and write the agent, the MCP server, the
Dockerfiles, and the manifests.

## Building the brief

With Tectonic and Pygments (`pygmentize`) on `PATH`, run:

```bash
cd briefs
tectonic -X compile -Z shell-escape -Z shell-escape-cwd=. hw3.tex
```

## Repository contents

| File | What it is |
|---|---|
| `briefs/hw3.pdf` | The assignment brief |
| `config.schema.json` | JSON Schema for the config your agent reads (`--config`, TOML). It changes the HW2 keys for the model, `[run]`, `[checkpoint]`, `[postgres]`, and `[mcp] url`. |
| `report.schema.json` | JSON Schema your `report.json` must validate against |
| `trace.schema.json` | JSON Schema each line of your `trace.jsonl` must validate against |
| `ledger.schema.json` | JSON Schema each line of your ledger export must validate against |
| `cluster/kind-config.yaml` | The staff KIND cluster. Test your stack on it before you submit. |
| `briefs/scan/` | The `[scan]` block for each target, and `counts.json` with the alert counts |
| `tests/` | Staff checks of the schemas, the examples, the brief, and the scan counts |

Examples, in `examples/`:

- `config.example.toml`: a valid config. The model URL and name are placeholders, and the key and password fields name environment variables.
- `report.example.json`: an example `report.json` with placeholder rationales.
- `trace.example.jsonl`: an example trace that shows a resume.
- `ledger.example.jsonl`: an example ledger export.
- `k8s/statefulset.example.yaml`: a StatefulSet with a headless Service and `volumeClaimTemplates`.
- `k8s/job-init.example.yaml`: a Job with an init container that waits for a port.

The two Kubernetes examples show patterns only. They are not the HW3 stack.
Never put secrets in a config file or in any other file in your repository.

## Running the staff tests

The tests use Python 3.12. The scan-count tests clone each pinned target and
run Bandit, so they need network access.

```bash
python3.12 -m venv .venv
.venv/bin/pip install pytest jsonschema pyyaml bandit==1.9.4
.venv/bin/pytest
```

## Test on the staff cluster

Create the staff cluster from the repository root. Deploy your stack on it
before you submit.

```bash
kind create cluster --config cluster/kind-config.yaml
```

## Staff deployment steps

Your own `README.md` must tell staff how to do these steps. Give the exact
commands, in order, from a fresh clone to a finished run (brief, Section
"README"):

1. Build each image with `docker build`.
2. Load each image with `kind load docker-image`. The staff cluster cannot pull from a team registry.
3. Make the two Secrets, for the team key and the Postgres password. Use `kubectl create secret generic` from environment variables that staff set. Or use a Kustomize `secretGenerator` that reads a git-ignored `k8s/.env`. Never commit a Secret value.
4. Apply the manifests. Use one file with `kubectl apply -f k8s/app.yaml`, or Kustomize with `kubectl apply -k k8s/`. Staff do not accept Helm.
5. Copy the pinned target source to the input PVC.
6. Start a run with one command that reads `HW3_RUN_ID` and applies the agent Job. Keep the Job outside the main apply, for example in `k8s/run/agent-job.yaml`. The same command writes `HW3_RUN_ID` into `[run] id` of the agent config. For example, run `sed` on the config, then `kubectl create configmap --from-file`.
7. Get `report.json`, `trace.jsonl`, and the ledger export.

The agent container runs a small init as PID 1. Your README names the command
that finds the agent PID (brief, Section "How staff test the deployment").
