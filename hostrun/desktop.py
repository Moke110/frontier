"""Native Frontier desktop: agent conversations and the resident console."""
from __future__ import annotations
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, simpledialog, messagebox
from pathlib import Path
from hostrun import console, console_events, embedded_agent, layout


class Desktop:
    def __init__(self, root, resolved):
        self.root, self.resolved = root, resolved
        self.activation = Path(resolved['runtime']) / 'desktop.activate'
        self.home = Path(resolved['runtime'])
        self.events, self.answers = queue.Queue(), queue.Queue()
        self.closed = False
        self.console_finished = False
        self.cancelled = threading.Event()
        self.process = None
        self.busy = False
        self.history = []
        root.title('Frontier — Research Agent')
        root.geometry('1280x820')
        root.minsize(920, 600)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', padding=8)
        bar = ttk.Frame(root, padding=12)
        bar.pack(fill='x')
        ttk.Label(bar, text='FRONTIER', font=('Segoe UI', 18, 'bold')).pack(side='left')
        ttk.Button(bar, text='模型设置', command=self.settings).pack(side='right')
        ttk.Button(bar, text='显示 / 隐藏 Console', command=self.toggle).pack(side='right')
        self.panes = ttk.Panedwindow(root, orient='horizontal')
        self.panes.pack(fill='both', expand=True, padx=12, pady=8)
        left = ttk.Frame(self.panes, padding=8)
        self.panes.add(left, weight=1)
        ttk.Button(left, text='+ 新建会话', command=self.new_chat).pack(fill='x')
        self.sessions = tk.Listbox(left, width=22, borderwidth=0, font=('Segoe UI', 11))
        self.sessions.pack(fill='both', expand=True, pady=12)
        self.sessions.bind('<<ListboxSelect>>', self.select_chat)
        self.store = self.home / 'desktop' / 'sessions.json'
        try:
            self.chats = json.loads(self.store.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.chats = []
        self.current = None
        center = ttk.Frame(self.panes, padding=8)
        self.panes.add(center, weight=5)
        ttk.Label(center, text='研究助手', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        self.chat = scrolledtext.ScrolledText(center, wrap='word', font=('Segoe UI', 11), state='disabled', borderwidth=0)
        self.chat.pack(fill='both', expand=True, pady=12)
        self.prompt = tk.Text(center, height=4, wrap='word', font=('Segoe UI', 11))
        self.prompt.pack(fill='x')
        self.prompt.bind('<Control-Return>', lambda _: self.send())
        actions = ttk.Frame(center)
        actions.pack(fill='x', pady=8)
        self.status = ttk.Label(actions, text='就绪 · Ctrl+Enter 发送')
        self.status.pack(side='left')
        ttk.Button(actions, text='停止', command=self.stop).pack(side='right')
        ttk.Button(actions, text='发送', command=self.send).pack(side='right')
        self.sidebar = ttk.Frame(self.panes, padding=8)
        self.panes.add(self.sidebar, weight=3)
        ttk.Label(self.sidebar, text='Frontier Console', font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        self.log = scrolledtext.ScrolledText(self.sidebar, width=42, state='disabled', wrap='word', bg='#18212c', fg='#dce6ed', font=('Consolas', 10))
        self.log.pack(fill='both', expand=True, pady=12)
        self.command = ttk.Entry(self.sidebar)
        self.command.pack(fill='x')
        self.command.bind('<Return>', self.submit_console)
        ttk.Button(self.sidebar, text='执行 / 提交回答', command=self.submit_console).pack(fill='x', pady=6)
        ttk.Label(self.sidebar, text='/frontier-help 查看命令\n初始化和审阅问题请在此回答').pack(anchor='w')
        self.refresh_sessions()
        if self.chats:
            self.current = 0
            self.render_chat()
        else:
            self.new_chat()
        root.protocol('WM_DELETE_WINDOW', self.close)
        threading.Thread(target=self.run_console, daemon=True).start()
        root.after(60, self.poll)

    def append(self, widget, text):
        widget.configure(state='normal')
        widget.insert('end', text)
        widget.see('end')
        widget.configure(state='disabled')

    def save(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        temp = self.store.with_suffix('.tmp')
        temp.write_text(json.dumps(self.chats, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.store)

    def refresh_sessions(self):
        self.sessions.delete(0, 'end')
        for chat in self.chats:
            self.sessions.insert('end', chat['title'])

    def new_chat(self):
        if self.busy:
            return
        self.chats.insert(0, {'title': '新会话', 'messages': []})
        self.current = 0
        self.refresh_sessions()
        self.render_chat()
        self.save()

    def select_chat(self, _):
        if not self.busy and self.sessions.curselection():
            self.current = self.sessions.curselection()[0]
            self.render_chat()

    def render_chat(self):
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.chat.configure(state='disabled')
        for m in self.chats[self.current]['messages']:
            self.append(self.chat, f"{m['role']}\n{m['text']}\n\n")

    def toggle(self):
        if str(self.sidebar) in self.panes.panes():
            self.panes.forget(self.sidebar)
        else:
            self.panes.add(self.sidebar, weight=3)

    def settings(self):
        if self.busy:
            return
        facts = embedded_agent.runtime(self.home, code=Path(self.resolved['code']))
        provider = simpledialog.askstring('模型', 'Provider', initialvalue=facts['provider'] or 'openai', parent=self.root)
        if not provider:
            return
        model = simpledialog.askstring('模型', '模型名称', initialvalue=facts['model'], parent=self.root)
        if not model:
            return
        url = simpledialog.askstring('模型', '兼容接口 Base URL（可留空）', parent=self.root)
        if url is None:
            return
        key = simpledialog.askstring('模型', 'API Key', show='*', parent=self.root)
        if not key:
            return
        try:
            embedded_agent.configure(self.home, provider=provider, model=model, api_key=key, base_url=url)
            self.status.configure(text='模型配置已保存')
        except Exception as exc:
            messagebox.showerror('配置失败', str(exc), parent=self.root)

    def send(self):
        text = self.prompt.get('1.0', 'end').strip()
        if self.busy or not text:
            return
        self.busy = True
        self.cancelled.clear()
        self.prompt.delete('1.0', 'end')
        chat = self.chats[self.current]
        if not chat['messages']:
            chat['title'] = text[:24]
            self.refresh_sessions()
        chat['messages'].append({'role': 'You', 'text': text})
        self.render_chat()
        self.append(self.chat, 'Frontier\n')
        self.response = ''
        self.save()
        self.status.configure(text='Agent 正在运行…')
        task = '\n\n'.join(m['role'] + ': ' + m['text'] for m in chat['messages'])
        threading.Thread(target=self.run_agent, args=(task,), daemon=True).start()

    def run_agent(self, task):
        try:
            argv = embedded_agent.argv(self.home, task, kind='agent', code=Path(self.resolved['code']))
            env = dict(os.environ, FRONTIER_PYTHON=sys.executable)
            self.process = subprocess.Popen(argv, cwd=self.resolved['code'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            # Drain stderr without exposing provider credentials in UI logs.
            threading.Thread(target=lambda p=self.process: p.stderr.read(), daemon=True).start()
            if self.cancelled.is_set():
                self.process.terminate()
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                self.events.put(('agent', event))
            code = self.process.wait()
            if code:
                self.events.put(('agent', {'type': 'error', 'message': f'Agent 退出 ({code})'}))
        except Exception as exc:
            self.events.put(('agent', {'type': 'error', 'message': str(exc)}))
        finally:
            self.process = None
            self.events.put(('done', None))

    def stop(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def submit_console(self, _=None):
        value = self.command.get()
        self.command.delete(0, 'end')
        self.command.configure(show='')
        self.answers.put(value)

    def read(self, prompt=''):
        if self.closed:
            raise EOFError
        self.events.put(('prompt', prompt))
        value = self.answers.get()
        if value is None:
            raise EOFError
        return value

    def write(self, text):
        self.events.put(('log', text))

    def flush(self):
        pass

    def run_console(self):
        try:
            from hostrun import update_kb_review
            result = console.serve(self.home, resolved=self.resolved, isatty=lambda: True, reader=self.read, out=self, set_title=lambda _: True, events=console_events.live,
                review=lambda home, service=None: update_kb_review.run(home, service=service, out=self, isatty=lambda: True, key_reader=lambda: self.read('审阅选项：')))
            self.write('\nConsole: ' + str(result.get('reason', 'stopped')) + '\n')
        except Exception as exc:
            self.write('\nConsole error: ' + str(exc) + '\n')
        finally:
            self.events.put(('console_done', None))

    def poll(self):
        if self.activation.exists():
            self.activation.unlink(missing_ok=True)
            self.root.deiconify()
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(200, lambda: self.root.attributes('-topmost', False))
            self.root.focus_force()
        for _ in range(250):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.append(self.log, data)
            elif kind == 'prompt':
                self.command.configure(show='*' if 'key' in data.lower() else '')
            elif kind == 'agent':
                if data['type'] == 'text':
                    self.response += data['text']
                    self.append(self.chat, data['text'])
                elif data['type'] == 'error':
                    self.response += '\n错误：' + data['message']
                    self.append(self.chat, '\n错误：' + data['message'])
                elif data['type'] in ('tool_call', 'tool_result'):
                    self.append(self.log, '\nAgent ' + data['type'] + ': ' + data['name'] + '\n')
            elif kind == 'done':
                self.busy = False
                self.chats[self.current]['messages'].append({'role': 'Frontier', 'text': self.response})
                self.save()
                self.status.configure(text='就绪')
            elif kind == 'console_done':
                self.console_finished = True
                self.command.configure(state='disabled')
                if self.closed:
                    self.root.destroy()
                    return
        self.root.after(60, self.poll)

    def close(self):
        self.closed = True
        self.stop()
        if self.console_finished:
            self.root.destroy()
            return
        self.answers.put(None)
        self.status.configure(text='正在关闭服务…')
        self.root.after(10000, self.root.destroy)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--code', required=True)
    parser.add_argument('--archive', required=True)
    args = parser.parse_args()
    resolved = layout.resolve(code=args.code, archive=args.archive)
    layout.ensure(resolved)
    layout.remember(resolved)
    layout.export(resolved)
    from common import file_lock
    root = tk.Tk()
    with file_lock(Path(resolved['runtime']) / 'desktop.lock', blocking=False) as acquired:
        if not acquired:
            root.withdraw()
            (Path(resolved['runtime']) / 'desktop.activate').touch()
            root.destroy()
            return
        Desktop(root, resolved)
        root.deiconify()
        root.lift()
        root.mainloop()


if __name__ == '__main__':
    main()
