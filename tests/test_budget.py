import ast
import io
import ipaddress
import re
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNBUDGETED = ("docs/", "eval/datasets/")
MAX_FILES, MAX_ML_FILES, MAX_COMMENTS = 100, 10, 5
PYTHON_BUDGETS = {("app/", "eval/", "load/"): 1150, ("ml/",): 450, ("ops/",): 100}
MAX_TEST_LINES, MAX_BICEP_LINES, MAX_TYPESCRIPT_LINES = 850, 490, 800
IDENTIFIERS = {
    "GUID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "Azure host": re.compile(
        r"[a-z0-9-]+\.(?:azurecontainerapps\.io|services\.ai\.azure\.com|openai\.azure\.com|"
        r"cognitiveservices\.azure\.com|inference\.ml\.azure\.com|azurecr\.io)",
        re.I,
    ),
    "local path": re.compile(r"(?:\b[a-z]:[\\/]|/[a-z]/)users[\\/]", re.I),
}
BUILT_IN_ROLES = re.compile(
    r"7f951dda-4ed3-4680-a7ca-43fe172d538d|f6c7c914-8db3-469d-8ca1-694a8f32e121|ba92f5b4-2d11-453d-a403-e96b0029c9fe|"
    r"2a2b9908-6ea1-4ae2-8e65-a410df84e7d1|5e0bd9bd-7b93-4f28-af87-19fc36ad61bd|53ca6127-db72-4b80-b1b0-d745d6d5456d|"
    r"3913510d-42f4-4e42-8a64-420c390055eb|f1a07417-d97a-45cb-824c-7a7467783830|00000000-0000-0000-0000-000000000002|"
    r"43d0d8ad-25c7-4714-9337-8ba259a9fe05"
)
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
SHA_PINNED = re.compile(r"uses:\s*(?:[\w.-]+/[\w./-]+@[0-9a-f]{40}\b|\./\.github/actions/)")


def repository_files() -> list[str]:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    names = subprocess.run(command, capture_output=True, text=True, check=True, cwd=ROOT).stdout.splitlines()
    return sorted(name for name in set(names) if (ROOT / name).is_file())


def budgeted(*suffixes: str, under: str | tuple[str, ...] = "") -> list[Path]:
    names = [n for n in repository_files() if not n.startswith(UNBUDGETED) and n.startswith(under)]
    return [ROOT / n for n in names if not suffixes or Path(n).suffix in suffixes]


def lines(paths: list[Path]) -> int:
    return sum(1 for p in paths for line in p.read_text(encoding="utf-8").splitlines() if line.strip())


def test_file_budgets() -> None:
    assert len(budgeted()) <= MAX_FILES, f"{len(budgeted())} files"
    assert len(budgeted(under="ml/")) <= MAX_ML_FILES, f"{len(budgeted(under='ml/'))} files in ml/"


def test_line_budgets() -> None:
    python = budgeted(".py")
    for folder, limit in PYTHON_BUDGETS.items():
        assert lines(budgeted(".py", under=folder)) <= limit, f"{folder} is over {limit} lines"
    others = [p for p in python if not p.relative_to(ROOT).as_posix().startswith(sum(PYTHON_BUDGETS, ()))]
    assert lines(others) <= MAX_TEST_LINES, f"{lines(others)} test lines"
    assert lines(budgeted(".bicep", ".bicepparam")) <= MAX_BICEP_LINES
    assert lines(budgeted(".ts", ".tsx")) <= MAX_TYPESCRIPT_LINES


def test_python_craft() -> None:
    comments = 0
    for path in budgeted(".py"):
        source = path.read_text(encoding="utf-8")
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        comments += sum(1 for token in tokens if token.type == tokenize.COMMENT)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ExceptHandler):
                caught = node.type.id if isinstance(node.type, ast.Name) else ""
                blind = node.type is None or caught in ("Exception", "BaseException")
                assert not blind, f"{path.name}:{node.lineno} catches everything"
    assert comments <= MAX_COMMENTS, f"{comments} comments"
    assert not [n for n in repository_files() if n.endswith(".ipynb")], "a notebook is part of the system"


def test_dependencies_and_actions_are_pinned() -> None:
    for requirements in ROOT.glob("requirements*.txt"):
        for pin in requirements.read_text(encoding="utf-8").splitlines():
            assert not pin or pin.startswith("-r ") or "==" in pin, f"unpinned {pin}"
    for workflow in (ROOT / ".github").rglob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"\buses:", line) or SHA_PINNED.search(line), f"{workflow.name}: {line.strip()}"


def test_no_identifiers() -> None:
    for name in repository_files():
        data = (ROOT / name).read_bytes()
        if b"\0" in data:
            continue
        text = BUILT_IN_ROLES.sub("", data.decode("utf-8"))
        for kind, pattern in IDENTIFIERS.items():
            assert not pattern.search(text), f"{name} contains a {kind}"
        public = [ip for ip in IPV4.findall(text) if ipaddress.ip_address(ip).is_global]
        assert not public, f"{name} contains a public IP address"
