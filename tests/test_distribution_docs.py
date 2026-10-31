"""Offline checks for the distribution-package documentation switch (#99).

These tests read the user-facing documents and the runtime skill reference and
compare them with the CLI the code actually ships.  They never run an install
and never touch the network: the point is that the documented path, the command
names and the release conventions stay truthful as the code moves.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
ACCEPTANCE = ROOT / "docs" / "acceptance" / "README.md"
ADR = ROOT / "docs" / "adr" / "0010-distribution-packages-for-installation.md"
SKILL = ROOT / "skills" / "frontier-run" / "SKILL.md"
INSTALLATION = ROOT / "skills" / "frontier-run" / "references" / "installation.md"
WORKFLOW = ROOT / "skills" / "frontier-run" / "references" / "workflow.md"

POINTER_LABELS = (
    "发行来源",
    "发行版本",
    "发行渠道",
    "制品摘要",
    "发行包来源",
    "源码提交",
    "工作区改动",
    "源码来源",
    "技能摘要",
    "安装锁",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, title: str) -> str:
    """Return the body of the first ``## `` section whose heading contains title."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and title in line:
            start = index + 1
            break
    assert start is not None, f"missing section {title!r}"
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def _walk_subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # argparse has no public walker
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _subcommand_parser(*path: str) -> argparse.ArgumentParser:
    from hostrun.cli import build_parser

    parser = build_parser()
    for part in path:
        choices = _walk_subparsers(parser)
        assert part in choices, f"CLI does not accept {part!r} after {path!r}"
        parser = choices[part]
    return parser


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    options: set[str] = set()
    for action in parser._actions:
        options.update(action.option_strings)
    return options


def _code_spans(text: str) -> list[str]:
    return [span.strip() for span in re.findall(r"`([^`\n]+)`", text)]


_INSTALL_CHOICES = {
    "check",
    "status",
    "report",
    "migrate",
    "record",
    "package",
    "verify",
    "rollback",
    "workspace",
    "toolchain",
    "skill",
    "locate",
}
_CONSOLE_CHOICES = {"control", "install"}
_CONTROL_ACTIONS = {"start", "stop", "status", "push"}


def _assert_commands_exist(text: str, label: str) -> None:
    for span in _code_spans(text):
        for match in re.finditer(r"\binstall\s+([a-z][a-z-]*)", span):
            name = match.group(1)
            assert name in _INSTALL_CHOICES, f"{label}: unknown install command {name!r} in `{span}`"
            _subcommand_parser("install", name)
        for match in re.finditer(r"\bconsole\s+([a-z][a-z-]*)", span):
            name = match.group(1)
            assert name in _CONSOLE_CHOICES, f"{label}: unknown console command {name!r} in `{span}`"
            parser = _subcommand_parser("console", name)
            if name == "control":
                action = re.search(r"\bconsole\s+control\s+([a-z][a-z-]*)", span)
                if action:
                    assert action.group(1) in _CONTROL_ACTIONS, (
                        f"{label}: unknown console control action {action.group(1)!r} in `{span}`"
                    )


def test_readme_install_section_is_the_package_user_path() -> None:
    section = _section(_read(README), "安装")
    lowered = section.lower()

    for forbidden in ("git clone", "uv venv", "uv pip", "pip install"):
        assert forbidden not in lowered, f"user install must not require {forbidden!r}"

    for expected in (
        "install package",
        "install verify",
        "install report",
        "install rollback",
        "frontier.cmd",
        "/frontier-init",
        "Get-FileHash",
        "Expand-Archive",
        "--digest",
        "sha256",
        "releases/index.json",
    ):
        assert expected.lower() in lowered, f"user install is missing {expected!r}"

    assert "发行包" in section
    assert "不需要 git" in section or "没有 git" in section


def test_readme_documents_the_source_install_developer_path() -> None:
    text = _read(README)
    assert "源码安装" in text
    assert "install workspace" in text
    assert "install toolchain" in text
    assert "install skill" in text
    assert "git clone" in text  # only the developer section may use it

    package_section = text.index("## 安装")
    developer_section = text.index("## 开发者")
    assert package_section < developer_section


def test_installation_reference_names_both_paths_with_prerequisites() -> None:
    text = _read(INSTALLATION)
    assert "发行包安装" in text
    assert "源码安装" in text
    assert "前置条件" in text

    for command in (
        "install package",
        "install verify",
        "install report",
        "install rollback",
        "install workspace",
        "install toolchain",
        "install skill",
        "console install",
    ):
        assert command in text, f"installation reference is missing {command!r}"

    for label in POINTER_LABELS:
        assert label in text, f"installation reference does not document pointer field {label!r}"

    assert "内置运行时" in text
    assert "uv" in text  # the developer prerequisites are stated explicitly
    assert "不需要 git" in text or "无 git" in text


def test_skill_entry_leads_with_the_distribution_package() -> None:
    text = _read(SKILL)
    description = text.split("---", 2)[1]
    assert "Deploy a private uv environment" not in description
    assert "distribution package" in description

    for label in POINTER_LABELS:
        assert label in text, f"SKILL.md does not describe pointer field {label!r}"
    assert "源码安装" in text or "source checkout" in text


def test_agents_documents_tag_and_channel_rules() -> None:
    text = _read(AGENTS)
    for expected in (
        "vMAJOR.MINOR.PATCH",
        "-rc.N",
        "prerelease",
        ".github/workflows/release.yml",
        "releases/index.json",
        "github-actions[bot]",
        "workflow_dispatch",
    ):
        assert expected in text, f"AGENTS.md is missing {expected!r}"

    assert "270 passed" not in text
    assert re.search(r"\d+ passed, 3 skipped", text), "AGENTS.md has no current green-suite baseline"


def test_latest_suite_count_agrees_between_agents_and_acceptance() -> None:
    agents_count = re.search(r"(\d+) passed, 3 skipped", _read(AGENTS))
    assert agents_count, "AGENTS.md has no suite count"
    section = _section(_read(ACCEPTANCE), "2026-10-31 发行包安装验收")
    acceptance_counts = set(re.findall(r"\*\*(\d+) passed, 3 skipped\*\*", section))
    assert acceptance_counts, "acceptance section has no suite count"
    assert agents_count.group(1) in acceptance_counts


def test_acceptance_records_the_distribution_items_honestly() -> None:
    """Real evidence is recorded where it exists; gaps stay visibly untested."""
    text = _read(ACCEPTANCE)
    assert "## 2026-10-31" in text
    section = _section(text, "2026-10-31")
    assert "spec #92" in section
    assert "ADR 0010" in section
    assert "verified" in section.lower()
    assert "untested" in section.lower()
    assert section.lower().count("untested") >= 2
    # /frontier-init was deliberately not executed and must stay untested.
    assert "`/frontier-init` 在发行包安装上走完全流程 | `untested`" in section
    assert "真实执行证据" in section


def test_adr_status_records_the_implementation_on_this_branch() -> None:
    text = _read(ADR)
    assert "## 实现状态" in text
    assert "2026-10-31" in text
    assert "#93–#100" in text
    assert "docs/acceptance" in text
    assert "实现未开始" not in text


def test_rollback_docs_do_not_claim_a_pointer_only_butterfly() -> None:
    """The implementation swaps package files from the retained tree (#92)."""
    for path in (
        ROOT / "contracts" / "README.md",
        ADR,
        INSTALLATION,
        ACCEPTANCE,
    ):
        text = _read(path)
        assert "不重新下载" in text, f"{path} does not state rollback skips re-download"
        assert "替换包文件" in text, f"{path} does not state rollback swaps package files"


def test_workflow_reference_no_longer_requires_a_source_checkout() -> None:
    text = _read(WORKFLOW)
    assert "发行包" in text
    assert "frontier.cmd" in text
    assert "内置运行时" in text


def test_documented_commands_match_the_cli() -> None:
    _assert_commands_exist(_read(README), "README.md")
    _assert_commands_exist(_read(INSTALLATION), "installation.md")
    _assert_commands_exist(_read(SKILL), "SKILL.md")


def test_documented_flags_exist_on_their_subcommands() -> None:
    package_options = _option_strings(_subcommand_parser("install", "package"))
    assert {"--from", "--digest", "--sha256", "--channel"} <= package_options
    assert {"--to"} <= _option_strings(_subcommand_parser("install", "rollback"))
    assert {"--root", "--target"} <= _option_strings(_subcommand_parser("install", "skill"))
    assert {"--dsh"} <= _option_strings(_subcommand_parser("console", "install"))
    assert {"start", "stop", "status", "push"} <= set(
        _walk_subparsers(_subcommand_parser("console", "control"))
    )

    installation = _read(INSTALLATION)
    for example in (
        "install package --from",
        "install verify",
        "install report",
        "install rollback",
        "install skill --root",
        "console install --dsh",
    ):
        assert example in installation, f"installation reference lacks {example!r}"


def test_no_unimplemented_banner_remains() -> None:
    for path in (README, AGENTS, ACCEPTANCE, ADR, SKILL, INSTALLATION, WORKFLOW):
        text = _read(path)
        assert "代码尚未实现" not in text, f"{path} still carries an unimplemented banner"
