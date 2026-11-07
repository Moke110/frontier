import queue
import threading
import tkinter as tk
from hostrun.desktop import Desktop


def test_desktop_sessions_and_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(Desktop, 'run_console', lambda self: None)
    root = tk.Tk()
    root.withdraw()
    app = Desktop(root, {'runtime': str(tmp_path), 'code': str(tmp_path), 'archive': str(tmp_path / 'archive')})
    try:
        app.chats[0]['messages'] = [{'role': 'You', 'text': '你好'}]
        app.save()
        assert '你好' in app.store.read_text(encoding='utf-8')
        app.response = ''
        app.busy = True
        app.events.put(('agent', {'type': 'text', 'text': '测试回复'}))
        app.events.put(('done', None))
        app.poll()
        assert not app.busy
        assert app.chats[0]['messages'][-1]['text'] == '测试回复'
        app.toggle()
        assert str(app.sidebar) not in app.panes.panes()
        app.toggle()
        assert str(app.sidebar) in app.panes.panes()
        app.new_chat()
        assert len(app.chats) == 2
    finally:
        root.destroy()


def test_console_answers_and_close():
    app = Desktop.__new__(Desktop)
    app.closed = False
    app.events = queue.Queue()
    app.answers = queue.Queue()
    app.answers.put('yes')
    assert app.read('question') == 'yes'
    app.closed = True
    import pytest
    with pytest.raises(EOFError):
        app.read()
