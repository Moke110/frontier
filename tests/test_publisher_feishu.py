"""Offline contract tests for the reusable bounded event consumer (issue #63).

No real ``lark-cli``, no network, no credentials: every consumer test injects a
fake ``popen`` and pins ``_cli_command``.  The live ``event consume`` argv,
``[event] ready event_key=...`` stderr marker and exit-code meanings come from
``docs/acceptance/README.md`` (lines 30 and 115) and stay ``untested`` against a
real CLI here.
"""

from __future__ import annotations

import io
import threading

import pytest

from publisher import feishu

READY = "[event] ready event_key=im.message.receive_v1\n"


def _fake_popen(monkeypatch, proc):
    """Pin the CLI argv prefix and capture the fake process call."""
    calls = []

    def popen(argv, **kwargs):
        calls.append(([str(item) for item in argv], kwargs))
        return proc

    monkeypatch.setattr(feishu.subprocess, "Popen", popen)
    monkeypatch.setattr(feishu, "_cli_command", lambda: ["C:/bin/lark-cli"])
    return calls


class _FakeStdin:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _ListStdout:
    def __init__(self, lines):
        self._iterator = iter(lines)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iterator)

    def close(self):
        self.closed = True


class _GatedStdout:
    """The second line only arrives once stderr draining has made progress."""

    def __init__(self, lines, gate):
        self._lines = list(lines)
        self._gate = gate
        self._index = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._index >= len(self._lines):
            raise StopIteration
        if self._index == 1 and not self._gate.wait(timeout=5):
            raise AssertionError("stderr was not drained while stdout stayed open")
        line = self._lines[self._index]
        self._index += 1
        return line

    def close(self):
        self.closed = True


class _BlockingStdout:
    """Blocks like a hung ``lark-cli`` until ``terminate`` releases it."""

    def __init__(self, release):
        self._release = release
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        self._release.wait(timeout=5)
        raise StopIteration

    def close(self):
        self.closed = True


class _FakeProc:
    def __init__(self, stdout_lines=(), stderr_lines=(), returncode=0, stdout=None):
        self.pid = 4242
        self.stdin = _FakeStdin()
        self.stdout = stdout if stdout is not None else _ListStdout(stdout_lines)
        self.stderr = io.StringIO("".join(stderr_lines))
        self.returncode = returncode
        self.terminated = False
        self._release = threading.Event()

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode == 0:
            self.returncode = -15
        self._release.set()


class _BlockingProc(_FakeProc):
    def __init__(self):
        super().__init__(returncode=None)
        self.stdout = _BlockingStdout(self._release)


# ------------------------------------------------------------ argv / contract
def test_listen_events_puts_event_key_and_bounds_in_the_argv(monkeypatch):
    proc = _FakeProc()
    calls = _fake_popen(monkeypatch, proc)

    result = feishu.listen_events(
        identity="bot",
        event_key="im.message.receive_v1",
        max_events=3,
        timeout="30s",
    )

    argv, kwargs = calls[0]
    assert argv[:4] == ["C:/bin/lark-cli", "event", "consume", "im.message.receive_v1"]
    assert argv[argv.index("--as") + 1] == "bot"
    assert argv[argv.index("--max-events") + 1] == "3"
    assert argv[argv.index("--timeout") + 1] == "30s"
    assert kwargs["stdin"] is feishu.subprocess.PIPE
    assert kwargs["stdout"] is feishu.subprocess.PIPE
    assert kwargs["stderr"] is feishu.subprocess.PIPE
    assert result["ok"] is True
    assert result["reason"] == "ok"
    assert result["returncode"] == 0


def test_listen_events_streams_each_non_empty_stdout_line(monkeypatch):
    seen = []
    _fake_popen(monkeypatch, _FakeProc(stdout_lines=['{"a": 1}\n', "\n", '{"b": 2}\n']))

    result = feishu.listen_events(on_line=lambda line: seen.append(line) or True)

    assert seen == ['{"a": 1}', '{"b": 2}']
    assert result["events"] == 2
    assert result["ok"] is True


def test_default_event_keys_are_distinct(monkeypatch):
    calls = []

    def popen(argv, **kwargs):
        calls.append([str(item) for item in argv])
        return _FakeProc()

    monkeypatch.setattr(feishu.subprocess, "Popen", popen)
    monkeypatch.setattr(feishu, "_cli_command", lambda: ["C:/bin/lark-cli"])

    feishu.listen_events()
    list(feishu.consume_events())

    assert calls[0][3] == "im.message.receive_v1"
    assert calls[1][3] == "card.action.trigger"
    # The new API is bounded by default; the legacy one keeps the old CLI
    # default (no flag), so ``--timeout/--max-events`` only appear when given.
    assert calls[0][calls[0].index("--timeout") + 1] == "30s"
    assert "--max-events" not in calls[0]
    assert "--timeout" not in calls[1]
    assert "--max-events" not in calls[1]


# -------------------------------------------------------------- stderr/ready
def test_listen_events_exposes_the_ready_marker(monkeypatch):
    ready = []
    _fake_popen(monkeypatch, _FakeProc(stderr_lines=["starting\n", READY]))

    result = feishu.listen_events(
        event_key="im.message.receive_v1", on_ready=ready.append
    )

    assert result["ready"] is True
    assert result["ready_event_key"] == "im.message.receive_v1"
    assert ready == ["im.message.receive_v1"]


def test_listen_events_drains_stderr_while_stdout_is_still_running(monkeypatch):
    drained = []
    gate = threading.Event()

    def on_stderr(line):
        drained.append(line)
        if len(drained) >= 2:
            gate.set()

    stdout = _GatedStdout(['{"first": 1}\n', '{"second": 2}\n'], gate)
    _fake_popen(monkeypatch, _FakeProc(stdout=stdout, stderr_lines=["one\n", "two\n", READY]))

    result = feishu.listen_events(on_stderr=on_stderr)

    assert drained[:2] == ["one", "two"]
    assert result["ready"] is True
    assert result["events"] == 2


def test_listen_events_keeps_only_the_tail_of_stderr(monkeypatch):
    lines = [f"noise {index}\n" for index in range(100)] + ["fatal detail\n"]
    _fake_popen(monkeypatch, _FakeProc(stderr_lines=lines, returncode=5))

    result = feishu.listen_events()

    assert "fatal detail" in result["stderr_tail"]
    assert "noise 0" not in result["stderr_tail"]
    assert len(result["stderr_tail"]) <= feishu.STDERR_TAIL_CHARS


# --------------------------------------------------------- exit classification
@pytest.mark.parametrize(
    "code,kind,fatal,retryable",
    [
        (4, "transient", False, True),
        (5, "token_storage_lock", False, True),
        (1, "unknown", True, False),
    ],
)
def test_listen_events_classifies_nonzero_exit_codes(
    monkeypatch, code, kind, fatal, retryable
):
    _fake_popen(monkeypatch, _FakeProc(stderr_lines=["boom\n"], returncode=code))

    result = feishu.listen_events()

    assert result["ok"] is False
    assert result["returncode"] == code
    assert result["kind"] == kind
    assert result["reason"] == kind
    assert result["fatal"] is fatal
    assert result["retryable"] is retryable
    assert "boom" in result["stderr_tail"]


def test_listen_events_treats_a_bare_exit_3_as_a_lost_connection(monkeypatch):
    """Live 2026-10-30: exit 3 after a network i/o timeout, no scope marker."""
    _fake_popen(monkeypatch, _FakeProc(stderr_lines=["dial tcp i/o timeout\n"], returncode=3))

    result = feishu.listen_events()

    assert result["kind"] == "consume_lost"
    assert result["fatal"] is False
    assert result["retryable"] is True


def test_listen_events_keeps_the_scope_marker_exit_3_fatal(monkeypatch):
    _fake_popen(
        monkeypatch, _FakeProc(stderr_lines=["app_scope_not_applied\n"], returncode=3)
    )

    result = feishu.listen_events()

    assert result["kind"] == "app_scope_not_applied"
    assert result["fatal"] is True
    assert result["retryable"] is False


def test_classify_exit_distinguishes_scope_marker_from_a_lost_connection():
    codes = [
        feishu.classify_exit(0),
        feishu.classify_exit(3),
        feishu.classify_exit(3, detail="failed: app_scope_not_applied"),
        feishu.classify_exit(4),
        feishu.classify_exit(5),
        feishu.classify_exit(1),
    ]

    assert codes[0]["kind"] == "ok"
    assert [row["kind"] for row in codes[1:]] == [
        "consume_lost",
        "app_scope_not_applied",
        "transient",
        "token_storage_lock",
        "unknown",
    ]
    assert [row["retryable"] for row in codes] == [
        False,
        True,
        False,
        True,
        True,
        False,
    ]


# ------------------------------------------------------------ bounded stopping
def test_a_false_on_line_stops_the_bounded_chunk(monkeypatch):
    proc = _FakeProc(stdout_lines=['{"a": 1}\n', '{"b": 2}\n'])
    _fake_popen(monkeypatch, proc)
    seen = []

    def on_line(line):
        seen.append(line)
        return False

    result = feishu.listen_events(on_line=on_line)

    assert seen == ['{"a": 1}']
    assert result["ok"] is True
    assert result["reason"] == "stopped"
    assert result["stopped"] is True
    assert proc.terminated is True


def test_deadline_terminates_a_hung_consumer(monkeypatch):
    proc = _BlockingProc()
    _fake_popen(monkeypatch, proc)

    result = feishu.listen_events(deadline_seconds=0.05)

    assert result["timed_out"] is True
    assert result["ok"] is False
    assert result["reason"] == "timeout"
    assert proc.terminated is True


# ------------------------------------------------- legacy consume_events compat
def test_legacy_consume_events_keeps_positional_arguments(monkeypatch):
    calls = _fake_popen(monkeypatch, _FakeProc(stdout_lines=["line-1\n", "line-2\n"]))

    lines = list(feishu.consume_events("bot", 2, "10m", "im.message.receive_v1"))

    argv = calls[0][0]
    assert lines == ["line-1", "line-2"]
    assert argv[:4] == ["C:/bin/lark-cli", "event", "consume", "im.message.receive_v1"]
    assert argv[argv.index("--max-events") + 1] == "2"
    assert argv[argv.index("--timeout") + 1] == "10m"


def test_legacy_consume_events_raises_with_the_returncode(monkeypatch):
    _fake_popen(monkeypatch, _FakeProc(stderr_lines=["app_scope_not_applied\n"], returncode=3))

    with pytest.raises(feishu.FeishuError) as raised:
        list(feishu.consume_events())

    assert raised.value.returncode == 3
    assert "3" in str(raised.value)
