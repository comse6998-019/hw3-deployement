import json, pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
# Each "% OPEN:" comment names one value that has no result on the build day.
# These are the rows of the open-values table in the Task 6 brief.
OPEN_ROWS = {"feasibility task 2", "feasibility task 3", "feasibility task 5", "feasibility task 8"}
def brief(): return (ROOT / "briefs/hw3.tex").read_text()


def test_each_count_appears():
    counts = json.loads((ROOT / "briefs/scan/counts.json").read_text())
    text = brief()
    for target, count in counts.items():
        # Anchor each count to its row of the targets table.
        assert re.search(rf"{target}\.toml.*&\s*{count}\s*\\\\", text), target
    assert re.search(rf"^Total &.*&\s*{sum(counts.values())}\s*\\\\", text, re.M), "total"

def test_december_17_only_in_late_days_row():
    lines = [l for l in brief().splitlines() if "December 17" in l or "Dec 17" in l or "Dec. 17" in l]
    assert len(lines) == 1 and lines[0].lstrip().startswith("Late days &"), lines

def test_no_hw2_only_names():
    text = brief()
    assert "codeact" not in text.lower()
    assert "OpenShell sandbox exec" not in text and "openshell sandbox exec" not in text
    assert not re.search(r"\{required\}", text), "old box name"
    assert r"\newtcolorbox{mustbox}" in text

def test_open_comments_match_open_rows():
    found = re.findall(r"%\s*OPEN:\s*(.+)", brief())
    assert found, "no OPEN comments"
    names = {f.strip().split(".")[0].strip().lower() for f in found}
    assert names <= OPEN_ROWS, names - OPEN_ROWS
    assert names == OPEN_ROWS, OPEN_ROWS - names
