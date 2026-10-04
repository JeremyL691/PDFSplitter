from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
from tkinterdnd2 import DND_FILES, TkinterDnD
from pypdf import PdfReader
from PIL import Image, ImageTk
from .cli import default_output_dir
from .models import OCROptions, SplitPlan, SplitItem, TextBlock, Diagnostic, CancelledError
from .splitter import analyze_pdf, export_plan, validate_plan, rebuild_plan, sanitize_name
from .ocr import NativeClient, extract_pages, clear_cache
STATES = {'ready': 'Done', 'blank': 'Blank', 'error': 'Error'}

class PDFSplitterApp:

    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.root.title('PDFSplitter')
        self.root.geometry('1120x760')
        self.root.minsize(320, 480)
        self.queue = queue.Queue()
        self.documents = {}
        self.selected = None
        self.page_no = 1
        self.busy = False
        self.cancel = threading.Event()
        self.last_output_dir = None
        self.worker = None
        self.preview_lock = threading.Lock()
        self.shutdown = threading.Event()
        self.settings_open = False
        self.preview_id = 0
        self.preview_image = None
        self.preview_photo = None
        self.node_map = {}
        self.mode = None
        self.source = tk.StringVar(value='auto')
        self.ocr_mode = tk.StringVar(value='auto')
        self.language = tk.StringVar(value='mixed')
        self.dpi = tk.StringVar(value='300')
        self.depth = tk.StringVar()
        self.intro = tk.BooleanVar(value=True)
        self.theme = tk.StringVar(value='system')
        self.reduce_motion = tk.BooleanVar(value=False)
        self.accept = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Drop PDFs to analyze, review and export.')
        self.page_status = tk.StringVar()
        self.output = tk.StringVar()
        self.zoom = tk.IntVar(value=100)
        self.system_dark = False
        self.system_reduce = False
        self._build_ui()
        self._apply_theme()
        self.root.bind('<Configure>', self._resize)
        self.root.protocol('WM_DELETE_WINDOW', self._close)
        self.root.bind('<Control-s>', lambda e: self._save_plan())
        self.root.bind('<Command-s>', lambda e: self._save_plan())
        self.root.bind('<Escape>', lambda e: self._cancel())
        self.root.bind('<Alt-Left>', lambda e: self._flip(-1))
        self.root.bind('<Alt-Right>', lambda e: self._flip(1))
        self.root.after(100, self._poll_messages)
        threading.Thread(target=self._system_settings, daemon=True).start()

    def _build_ui(self):
        self.style = ttk.Style(self.root)
        self.style.theme_use('clam')
        self.outer = ttk.Frame(self.root, padding=12)
        self.outer.pack(fill='both', expand=True)
        self.header = header = ttk.Frame(self.outer)
        header.pack(fill='x')
        ttk.Label(header, text='PDFSplitter', font=('Helvetica Neue', 21, 'bold')).pack(side='left')
        self.subtitle = ttk.Label(header, text='Local OCR · Review · Split', font=('Helvetica Neue', 11))
        self.subtitle.pack(side='left', padx=12)
        self.actions = ttk.Frame(self.outer)
        self.actions.pack(fill='x', pady=8)
        actions = [('Choose PDF', self._choose_files), ('Load plan', self._load_plan), ('Save plan', self._save_plan), ('Export', self._export), ('Cancel', self._cancel), ('Settings', self._toggle_settings)]
        self.action_buttons = []
        for text, command in actions:
            b = ttk.Button(self.actions, text=text, command=command, width=8)
            self.action_buttons.append(b)
        self.settings = ttk.Frame(self.outer)
        self.settings.pack(fill='x', pady=(0, 8))
        self.setting_cells = []

        def option(label, variable, values, width=9, labels=None):
            cell = ttk.Frame(self.settings)
            ttk.Label(cell, text=label).pack(anchor='w')
            display = variable
            if labels:
                display = tk.StringVar(value=labels[variable.get()])
                reverse = {v: k for k, v in labels.items()}

                def from_display(*_):
                    if display.get() in reverse and variable.get() != reverse[display.get()]:
                        variable.set(reverse[display.get()])

                def from_value(*_):
                    if variable.get() in labels and display.get() != labels[variable.get()]:
                        display.set(labels[variable.get()])
                display.trace_add('write', from_display)
                variable.trace_add('write', from_value)
                values = [labels[v] for v in values]
            ttk.Combobox(cell, textvariable=display, values=values, state='readonly', width=width).pack(fill='x')
            self.setting_cells.append(cell)
        option('Detection', self.source, ['auto', 'outline', 'toc', 'scan'], labels={'auto': 'Auto', 'outline': 'Bookmarks', 'toc': 'Contents', 'scan': 'Headings'})
        option('OCR mode', self.ocr_mode, ['auto', 'off', 'force'], labels={'auto': 'Auto', 'off': 'Off', 'force': 'Force OCR'})
        option('Language', self.language, ['mixed', 'en', 'zh-Hans', 'zh-Hant'], 16, labels={'mixed': 'Mixed (EN / ZH)', 'en': 'English', 'zh-Hans': 'Simplified + EN', 'zh-Hant': 'Traditional + EN'})
        option('DPI', self.dpi, ['150', '300', '450'], 5)
        cell = ttk.Frame(self.settings)
        ttk.Label(cell, text='Section depth (auto)').pack(anchor='w')
        ttk.Entry(cell, textvariable=self.depth, width=8).pack(fill='x')
        self.setting_cells.append(cell)
        option('Theme', self.theme, ['system', 'light', 'dark'], 7, labels={'system': 'System', 'light': 'Light', 'dark': 'Dark'})
        self.theme.trace_add('write', lambda *_: self._apply_theme())
        self.extras = ttk.Frame(self.outer)
        self.extras.pack(fill='x')
        self.open_output = ttk.Button(self.extras, text='Open output', command=self._open_last_output, width=10)
        self.extra_controls = [ttk.Checkbutton(self.extras, text='Include intros', variable=self.intro), ttk.Checkbutton(self.extras, text='Reduce motion', variable=self.reduce_motion), self.open_output, ttk.Button(self.extras, text='Clear cache', command=self._clear_cache, width=10)]
        self.drop = tk.Canvas(self.outer, height=40, highlightthickness=0)
        self.drop.bind('<Configure>', lambda e: self._draw_drop())
        self.drop.pack(fill='x', pady=8)
        self.drop.drop_target_register(DND_FILES)
        self.drop.dnd_bind('<<Drop>>', self._on_drop)
        self.body = ttk.Frame(self.outer)
        self.body.pack(fill='both', expand=True)
        self.files_frame = ttk.Frame(self.body, padding=4)
        self.files = ttk.Treeview(self.files_frame, show='tree', selectmode='browse')
        self.files.pack(side='left', fill='both', expand=True)
        file_scroll = ttk.Scrollbar(self.files_frame, command=self.files.yview)
        file_scroll.pack(side='right', fill='y')
        self.files.configure(yscrollcommand=file_scroll.set)
        self.files.bind('<<TreeviewSelect>>', self._select_page)
        self.workbook = ttk.Notebook(self.body)
        self.ocr_tab = ttk.Frame(self.workbook)
        self.plan_tab = ttk.Frame(self.workbook, padding=4)
        self.workbook.add(self.ocr_tab, text='Page and text')
        self.workbook.add(self.plan_tab, text='Split plan')
        self.page_frame = ttk.Frame(self.ocr_tab, padding=4)
        self.text_frame = ttk.Frame(self.ocr_tab, padding=4)
        nav = ttk.Frame(self.page_frame)
        nav.pack(fill='x')
        ttk.Button(nav, text='Previous', command=lambda: self._flip(-1), width=8).pack(side='left')
        ttk.Button(nav, text='Next', command=lambda: self._flip(1), width=6).pack(side='left', padx=4)
        ttk.Combobox(nav, textvariable=self.zoom, values=[50, 75, 100, 150, 200], width=4, state='readonly').pack(side='right')
        self.zoom.trace_add('write', lambda *_: self._preview())
        preview_container = ttk.Frame(self.page_frame)
        preview_container.pack(fill='both', expand=True, pady=6)
        self.canvas = tk.Canvas(preview_container, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(preview_container, command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(preview_container, orient='horizontal', command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(xscrollcommand=horizontal.set)
        preview_container.rowconfigure(0, weight=1)
        preview_container.columnconfigure(0, weight=1)
        self.canvas.bind('<Button-1>', self._click_block)
        self.canvas.bind('<Configure>', lambda e: self._draw_preview())
        ttk.Label(self.text_frame, textvariable=self.page_status, wraplength=310).pack(fill='x')
        self.text = tk.Text(self.text_frame, wrap='word', undo=True, font=('Helvetica Neue', 12), height=8, padx=10, pady=10)
        self.text.pack(fill='both', expand=True, pady=6)
        self.text.bind('<ButtonRelease-1>', self._select_text)
        self.text.bind('<KeyRelease>', self._select_text)
        tools = ttk.Frame(self.text_frame)
        tools.pack(fill='x')
        ttk.Button(tools, text='Save text', command=self._edit_text, width=10).pack(side='left')
        ttk.Button(tools, text='Run OCR', command=self._reocr, width=8).pack(side='left', padx=4)
        more = ttk.Frame(self.text_frame)
        more.pack(fill='x', pady=4)
        ttk.Button(more, text='Candidates', command=self._candidates, width=10).pack(side='left')
        ttk.Button(more, text='Use new OCR', command=self._use_pending, width=10).pack(side='left', padx=4)
        ttk.Button(self.text_frame, text='Keep edits', command=self._keep_manual).pack(anchor='w')
        self.plan_actions = ttk.Frame(self.plan_tab)
        self.plan_actions.pack(fill='x')
        self.plan_buttons = []
        for label, cmd in [('Rebuild plan', self._rebuild), ('Edit', self._edit_item), ('Add', lambda: self._edit_item(new=True)), ('Exclude / restore', self._exclude), ('Merge', self._merge), ('Divide', self._split), ('Boundary', self._boundary)]:
            button = ttk.Button(self.plan_actions, text=label, command=cmd)
            self.plan_buttons.append(button)
        self.items = ttk.Treeview(self.plan_tab, columns=('start', 'end', 'pages'), show='tree headings', selectmode='extended')
        self.items.heading('#0', text='Chapters and titles')
        self.items.heading('start', text='Start')
        self.items.heading('end', text='End')
        self.items.heading('pages', text='Pages')
        for col in ['start', 'end', 'pages']:
            self.items.column(col, width=50, minwidth=35, stretch=False)
        self.items.column('#0', width=300, minwidth=120)
        self.items.pack(fill='both', expand=True, pady=6)
        self.items.bind('<Double-1>', lambda e: self._edit_item())
        self.warnings = tk.Text(self.plan_tab, height=4, wrap='word', font=('Helvetica Neue', 10))
        self.warnings.pack(fill='x')
        self.warnings.configure(state='disabled')
        self.export_row = export_row = ttk.Frame(self.outer)
        export_row.pack(fill='x', pady=6)
        ttk.Checkbutton(export_row, text='Accept reviewed nonfatal warnings', variable=self.accept).pack(anchor='w')
        out = ttk.Frame(export_row)
        out.pack(fill='x')
        ttk.Label(out, text='Output parent').pack(side='left')
        ttk.Entry(out, textvariable=self.output).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(out, text='Browse', command=self._choose_output).pack(side='right')
        self.progress = ttk.Progressbar(self.outer, mode='determinate')
        self.progress.pack(fill='x')
        self.status_label = ttk.Label(self.outer, textvariable=self.status, wraplength=1000)
        self.status_label.pack(fill='x', pady=4)
        self.logs = tk.Text(self.outer, height=3, wrap='word', font=('SF Mono', 10))
        self.logs.pack(fill='x')
        self.logs.configure(state='disabled')

    def _apply_theme(self):
        dark = self.theme.get() == 'dark' or (self.theme.get() == 'system' and self.system_dark)
        self.colors = {'bg': '#211e1c', 'panel': '#302b27', 'text': '#f4eee8', 'muted': '#c8bcb2', 'accent': '#d7884b', 'select': '#66432b'} if dark else {'bg': '#f4f1ea', 'panel': '#fffaf0', 'text': '#30251e', 'muted': '#6c625a', 'accent': '#a9541b', 'select': '#f2d7bd'}
        c = self.colors
        self.root.configure(bg=c['bg'])
        self.style.configure('.', background=c['bg'], foreground=c['text'], font=('Helvetica Neue', 11))
        self.style.configure('TButton', padding=(9, 6), background=c['panel'], foreground=c['text'], borderwidth=1)
        self.style.map('TButton', background=[('active', c['select'])])
        self.style.configure('Treeview', background=c['panel'], fieldbackground=c['panel'], foreground=c['text'], rowheight=27)
        self.style.map('Treeview', background=[('selected', c['select'])], foreground=[('selected', c['text'])])
        self.style.configure('TEntry', fieldbackground=c['panel'], foreground=c['text'])
        self.style.configure('TCombobox', fieldbackground=c['panel'], foreground=c['text'])
        self.style.map('TCombobox', fieldbackground=[('readonly', c['panel'])], foreground=[('readonly', c['text'])], selectbackground=[('readonly', c['panel'])], selectforeground=[('readonly', c['text'])])
        self.style.configure('TNotebook', background=c['bg'], borderwidth=0)
        self.style.configure('TNotebook.Tab', background=c['panel'], padding=(12, 7))
        self.style.map('TNotebook.Tab', background=[('selected', c['select'])], foreground=[('selected', c['text'])])
        self.style.configure('TProgressbar', background=c['accent'], troughcolor=c['panel'])
        for widget in [self.text, self.warnings, self.logs]:
            widget.configure(bg=c['panel'], fg=c['text'], insertbackground=c['text'], selectbackground=c['select'], relief='flat', highlightthickness=0)
        self.drop.configure(bg=c['bg'])
        self._draw_drop()
        self.canvas.configure(bg=c['panel'])
        self._draw_preview()

    def _draw_drop(self):
        if not hasattr(self, 'colors'):
            return
        c = self.colors
        w = max(40, self.drop.winfo_width())
        h = 40
        r = 12
        self.drop.delete('all')
        self.drop.create_polygon([r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0], smooth=True, fill=c['select'], outline='')
        self.drop.create_text(w / 2, h / 2, text='Drop PDFs here to analyze', fill=c['text'], font=('Helvetica Neue', 11))

    def _system_settings(self):
        try:
            with NativeClient() as client:
                self.queue.put(('settings', client.capabilities))
        except Exception as exc:
            self.queue.put(('log', f'Native helper: {exc}'))

    def _toggle_settings(self):
        self.settings_open = not self.settings_open
        self._layout_settings(self.root.winfo_width())

    def _layout_settings(self, width):
        if width >= 768 or self.settings_open:
            self.settings.pack(fill='x', pady=(0, 8), after=self.actions)
        else:
            self.settings.pack_forget()

    def _resize(self, event):
        if event.widget is not self.root:
            return
        width = event.width
        self.status_label.configure(wraplength=max(260, width - 40))
        self.outer.configure(padding=8 if width < 768 else 12)
        self._layout_settings(width)
        if width < 768:
            self.subtitle.pack_forget()
        elif not self.subtitle.winfo_manager():
            self.subtitle.pack(side='left', padx=12)
        extra_columns = 4 if width >= 768 else 2
        for index, control in enumerate(self.extra_controls):
            control.grid(row=index // extra_columns, column=index % extra_columns, sticky='w', padx=4, pady=2)
        mode = 'wide' if width >= 1024 else 'medium' if width >= 768 else 'small'
        columns = 6 if width >= 1024 else 4 if width >= 768 else 2
        for index, cell in enumerate(self.setting_cells):
            cell.grid(row=index // columns, column=index % columns, sticky='ew', padx=3, pady=2)
        for column in range(7):
            self.settings.columnconfigure(column, weight=1 if column < columns else 0)
        acols = 6 if width >= 768 else 3
        for index, button in enumerate(self.action_buttons):
            button.grid(row=index // acols, column=index % acols, sticky='ew', padx=2, pady=2)
        for column in range(6):
            self.actions.columnconfigure(column, weight=1 if column < acols else 0)
        plan_columns = 7 if width >= 1024 else 3 if width >= 768 else 2
        for index, button in enumerate(self.plan_buttons):
            button.grid(row=index // plan_columns, column=index % plan_columns, padx=2, pady=2)
        if mode == self.mode:
            return
        self.mode = mode
        for child in self.body.winfo_children():
            child.pack_forget()
        for child in [self.page_frame, self.text_frame]:
            child.pack_forget()
        if getattr(self, 'small_tabs', None):
            self.small_tabs.destroy()
            self.small_tabs = None
        if mode == 'wide':
            self.files_frame.pack(side='left', fill='y')
            self.files_frame.configure(width=200)
            self.files_frame.pack_propagate(False)
            self.workbook.pack(side='left', fill='both', expand=True, padx=(8, 0))
            self.page_frame.pack(side='left', fill='both', expand=True)
            self.text_frame.pack(side='right', fill='both')
            self.text_frame.configure(width=320)
            self.text_frame.pack_propagate(False)
        elif mode == 'medium':
            self.files_frame.pack(side='top', fill='x')
            self.files_frame.configure(height=90)
            self.files_frame.pack_propagate(False)
            self.workbook.pack(fill='both', expand=True)
            self.page_frame.pack(side='left', fill='both', expand=True)
            self.text_frame.pack(side='right', fill='both')
            self.text_frame.configure(width=280)
            self.text_frame.pack_propagate(False)
        else:
            self.files_frame.pack(side='top', fill='x')
            self.files_frame.configure(height=60)
            self.files_frame.pack_propagate(False)
            self.workbook.pack(fill='both', expand=True)
            self.small_tabs = ttk.Frame(self.ocr_tab)
            self.small_tabs.pack(fill='x')
            ttk.Button(self.small_tabs, text='Page', command=lambda: self._small_panel('page')).pack(side='left', expand=True, fill='x')
            ttk.Button(self.small_tabs, text='Text', command=lambda: self._small_panel('text')).pack(side='left', expand=True, fill='x')
            self._small_panel('page')
        self.status.set(self.status.get())

    def _small_panel(self, panel):
        self.page_frame.pack_forget()
        self.text_frame.pack_forget()
        frame = self.page_frame if panel == 'page' else self.text_frame
        frame.pack(fill='both', expand=True)
        frame.pack_propagate(True)

    def _log(self, text):
        self.logs.configure(state='normal')
        self.logs.insert('end', str(text) + '\n')
        self.logs.see('end')
        self.logs.configure(state='disabled')

    def _choose_files(self):
        files = filedialog.askopenfilenames(title='Choose PDF', filetypes=[('PDF', '*.pdf')])
        if files:
            self._start_jobs([Path(p) for p in files])

    def _parse_drop_paths(self, data):
        return [Path(p).expanduser() for p in self.root.tk.splitlist(data) if Path(p).suffix.lower() == '.pdf' and Path(p).is_file()]

    def _on_drop(self, event):
        paths = self._parse_drop_paths(str(event.data))
        if paths:
            self._start_jobs(paths)
        else:
            messagebox.showerror('PDFSplitter', 'Drop valid PDF files.')

    def _options(self):
        value = self.depth.get().strip()
        depth = int(value) if value else None
        if depth is not None and depth < 1:
            raise ValueError('Section depth must be a positive integer.')
        return (depth, OCROptions(self.ocr_mode.get(), self.language.get(), int(self.dpi.get())))

    def _start_jobs(self, paths):
        if self.busy:
            messagebox.showinfo('PDFSplitter', 'Wait for the current task or cancel it first.')
            return
        try:
            depth, options = self._options()
        except ValueError as exc:
            messagebox.showerror('PDFSplitter', str(exc))
            return
        for path in paths:
            key = str(path.resolve())
            if key not in self.documents:
                node = f'doc-{len(self.documents)}'
                self.documents[key] = {'node': node, 'plan': None, 'pages': {}, 'state': 'Analyzing', 'pending': {}}
                self.files.insert('', 'end', iid=node, text=path.name, open=True)
                self.node_map[node] = (key, 1)
            self.selected = key
        source = self.source.get()
        intro = self.intro.get()
        self.busy = True
        self.cancel.clear()
        self.progress['value'] = 0

        def worker():
            for path in paths:
                key = str(path.resolve())
                if self.cancel.is_set():
                    self.queue.put(('state', key, 'Cancelled'))
                    continue
                self.queue.put(('state', key, 'Analyzing'))
                try:
                    plan = analyze_pdf(path, source, intro, depth, ocr_options=deepcopy(options), cancel_token=self.cancel, progress_callback=lambda event, key=key: self.queue.put(('event', key, event)))
                    self.queue.put(('plan', key, plan))
                except CancelledError:
                    self.queue.put(('state', key, 'Cancelled'))
                except Exception as exc:
                    self.queue.put(('state', key, 'Failed'))
                    self.queue.put(('log', f'{path.name}: {exc}'))
            self.queue.put(('finished',))
        self.worker = threading.Thread(target=worker)
        self.worker.start()

    def _poll_messages(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == 'settings':
                    self.system_dark = msg[1].get('dark', False)
                    self.system_reduce = msg[1].get('reduce_motion', False)
                    self._apply_theme()
                    self.root.after(30000, lambda: threading.Thread(target=self._system_settings, daemon=True).start() if not self.shutdown.is_set() else None)
                elif kind == 'log':
                    self._log(msg[1])
                elif kind == 'state':
                    key, state = msg[1:]
                    self.documents[key]['state'] = state
                    self.files.item(self.documents[key]['node'], text=f'{Path(key).name} · {state}')
                    self.status.set(state)
                elif kind == 'event':
                    key, event = msg[1:]
                    doc = self.documents[key]
                    if event['stage'] == 'init':
                        for number in range(1, event['total'] + 1):
                            node = f"{doc['node']}-p{number}"
                            if not self.files.exists(node):
                                self.files.insert(doc['node'], 'end', iid=node, text=f'{number} · Pending')
                            self.node_map[node] = (key, number)
                    elif event['stage'] == 'page':
                        page = event['page']
                        doc['pages'][page.page_no] = page
                        node = f"{doc['node']}-p{page.page_no}"
                        title = f"{page.page_no} · {STATES.get(page.status, page.status)} · {('OCR' if page.source == 'ocr' else 'Native')}{(' · Cached' if page.cached else '')}"
                        if self.files.exists(node):
                            self.files.item(node, text=title)
                        else:
                            self.files.insert(doc['node'], 'end', iid=node, text=title)
                            self.node_map[node] = (key, page.page_no)
                        self.progress['value'] = 100 * len(doc['pages']) / event['total']
                        if self.selected == key and self.page_no == page.page_no:
                            self._show_text()
                            self._preview()
                    elif event['stage'] == 'ocr':
                        self.status.set(f"{Path(key).name}: processing page {event['page_no']}/{event['total']} pages")
                        node = f"{doc['node']}-p{event['page_no']}"
                        if self.files.exists(node):
                            self.files.item(node, text=f"{event['page_no']} · Recognizing")
                elif kind == 'plan':
                    key, plan = msg[1:]
                    self.documents[key]['plan'] = plan
                    self.documents[key]['pending'] = plan.pending_pages
                    self.documents[key]['pages'] = {p.page_no: p for p in plan.pages}
                    self.documents[key]['state'] = 'Review required' if any((w.severity != 'info' for w in plan.warnings)) else 'Ready to export'
                    self.files.item(self.documents[key]['node'], text=f"{Path(key).name} · {self.documents[key]['state']}")
                    self.selected = key
                    self.page_no = 1
                    self._show_plan()
                    self._show_text()
                    self._preview()
                elif kind == 'preview':
                    request, path = msg[1:]
                    if request == self.preview_id:
                        with Image.open(path) as image:
                            self.preview_photo = image.copy()
                        self._draw_preview()
                elif kind == 'preview_error':
                    if msg[1] == self.preview_id:
                        self.canvas.delete('all')
                        self.canvas.create_text(12, 12, text='Page preview unavailable\n' + msg[2], anchor='nw', width=max(100, self.canvas.winfo_width() - 24), fill=self.colors['text'])
                elif kind == 'reocr':
                    key, pages = msg[1:]
                    doc = self.documents[key]
                    plan = doc['plan']
                    for page in pages:
                        old = doc['pages'][page.page_no]
                        if any((b.source == 'user' for b in old.blocks)):
                            doc['pending'][page.page_no] = page
                            plan.warnings.append(Diagnostic('reocr_conflict', 'New OCR results saved for comparison. Choose which version to keep.', page_no=page.page_no))
                        else:
                            doc['pages'][page.page_no] = page
                            plan.pages[page.page_no - 1] = page
                    plan.dirty = True
                    doc['state'] = 'Rebuild required'
                    self._show_text()
                    self._show_plan()
                elif kind == 'exported':
                    key, result = msg[1:]
                    self.last_output_dir = result['output_dir']
                    self.documents[key]['state'] = 'Success'
                    self._log(f"Exported {result['split_count']} files: {self.last_output_dir}")
                    self.status.set(f'Export complete: {self.last_output_dir}')
                elif kind == 'finished':
                    self.busy = False
                    for key, doc in self.documents.items():
                        self.files.item(doc['node'], text=f"{Path(key).name} · {doc['state']}")
                    states = [d['state'] for d in self.documents.values()]
                    self.status.set('；'.join((f'{s} {states.count(s)}' for s in dict.fromkeys(states))) or 'Done')
                    self.progress['value'] = 0 if self.cancel.is_set() else 100
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _plan(self):
        return self.documents.get(self.selected, {}).get('plan')

    def _page(self):
        return self.documents.get(self.selected, {}).get('pages', {}).get(self.page_no)

    def _select_page(self, event=None):
        selection = self.files.selection()
        if not selection:
            return
        self.selected, self.page_no = self.node_map[selection[0]]
        self.accept.set(False)
        self._show_text()
        self._show_plan()
        self._preview()
        self._feedback()

    def _feedback(self):
        if self.reduce_motion.get() or self.system_reduce:
            return
        self.drop.itemconfigure('all', stipple='gray75')
        self.root.after(180, lambda: self._draw_drop() if self.drop.winfo_exists() else None)

    def _flip(self, delta):
        doc = self.documents.get(self.selected, {})
        count = len(doc.get('pages', {}))
        if count:
            self.page_no = max(1, min(count, self.page_no + delta))
            self._show_text()
            self._preview()

    def _show_text(self):
        page = self._page()
        self.text.delete('1.0', 'end')
        if not page:
            self.page_status.set('Select a page to review its text.')
            return
        self.text.insert('1.0', page.text)
        self.page_status.set(f'Page {page.page_no} · {STATES.get(page.status, page.status)} · {page.source}' + (f'\n{page.error}' if page.error else ''))

    def _preview(self):
        if not self.selected:
            return
        self.preview_id += 1
        request = self.preview_id
        path = Path(self.selected)
        number = self.page_no
        dpi = max(30, min(250, int(100 * self.zoom.get() / 100)))

        def worker():
            try:
                with self.preview_lock:
                    if request != self.preview_id or self.shutdown.is_set():
                        return
                    with NativeClient(self.shutdown) as client:
                        output = client.preview(path, number, 150)
                self.queue.put(('preview', request, output))
            except Exception as exc:
                self.queue.put(('preview_error', request, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _draw_preview(self):
        self.canvas.delete('all')
        if not self.preview_photo:
            return
        width = max(1, self.canvas.winfo_width() - 12)
        height = max(1, self.canvas.winfo_height() - 12)
        factor = min(width / self.preview_photo.width, height / self.preview_photo.height) * self.zoom.get() / 100
        size = (max(1, int(self.preview_photo.width * factor)), max(1, int(self.preview_photo.height * factor)))
        self.preview_image = ImageTk.PhotoImage(self.preview_photo.resize(size, Image.Resampling.LANCZOS))
        self.canvas.configure(scrollregion=(0, 0, size[0] + 12, size[1] + 12))
        self.canvas.create_image(6, 6, image=self.preview_image, anchor='nw')
        page = self._page()
        if page:
            for index, block in enumerate(page.blocks):
                if not block.bbox:
                    continue
                x, y, w, h = block.bbox
                pw = self.preview_image.width()
                ph = self.preview_image.height()
                self.canvas.create_rectangle(6 + x * pw, 6 + y * ph, 6 + (x + w) * pw, 6 + (y + h) * ph, outline=self.colors['accent'], width=1, tags=(f'block-{index}',))

    def _select_text(self, event=None):
        try:
            line = int(self.text.index('insert').split('.')[0]) - 1
        except ValueError:
            return
        page = self._page()
        if page:
            for index in range(len(page.blocks)):
                self.canvas.itemconfigure(f'block-{index}', width=3 if index == line else 1)

    def _click_block(self, event):
        for item in self.canvas.find_overlapping(self.canvas.canvasx(event.x) - 2, self.canvas.canvasy(event.y) - 2, self.canvas.canvasx(event.x) + 2, self.canvas.canvasy(event.y) + 2):
            for tag in self.canvas.gettags(item):
                if tag.startswith('block-'):
                    line = int(tag[6:]) + 1
                    self.text.mark_set('insert', f'{line}.0')
                    self.text.see(f'{line}.0')
                    self.text.focus_set()
                    self._select_text()
                    return

    def _edit_text(self):
        plan = self._plan()
        page = self._page()
        if not plan or not page or self.busy:
            return
        lines = self.text.get('1.0', 'end-1c').splitlines()
        old = deepcopy(page.blocks)
        page.blocks = [TextBlock(line, old[i].bbox if i < len(old) else None, None, 'user', old[i].candidates if i < len(old) else [], old[i].original_text or old[i].text if i < len(old) else None) for i, line in enumerate(lines)]
        if page.blocks and len(lines) != len(old):
            page.blocks[0].candidates.extend((asdict(b) for b in old))
        page.source = 'user'
        page.status = 'ready'
        page.error = None
        plan.dirty = True
        plan.warnings = [w for w in plan.warnings if not (w.code == 'page_error' and w.page_no == page.page_no)]
        self.documents[self.selected]['state'] = 'Rebuild required'
        self._show_plan()
        self.status.set('Text corrections saved. Rebuild the split plan.')

    def _reocr(self):
        plan = self._plan()
        if not plan or self.busy:
            return
        text = simpledialog.askstring('Run OCR', 'Page range, such as 1 or 2-5', initialvalue=str(self.page_no), parent=self.root)
        if not text:
            return
        try:
            parts = text.split('-')
            start = int(parts[0])
            end = int(parts[-1])
            numbers = list(range(start, end + 1))
            if not 1 <= start <= end <= plan.total_pages:
                raise ValueError('Page range is out of bounds.')
            _, options = self._options()
            options.mode = 'force'
        except ValueError as exc:
            messagebox.showerror('PDFSplitter', str(exc))
            return
        key = self.selected
        self.busy = True
        self.cancel.clear()

        def worker():
            try:
                pages, _ = extract_pages(Path(key), PdfReader(key), options, self.cancel, lambda e: self.queue.put(('event', key, e)) if e['stage'] == 'ocr' else None, numbers)
                self.queue.put(('reocr', key, pages))
            except CancelledError:
                self.queue.put(('state', key, 'Cancelled'))
            except Exception as exc:
                self.queue.put(('state', key, 'Failed'))
                self.queue.put(('log', str(exc)))
            finally:
                self.queue.put(('finished',))
        self.worker = threading.Thread(target=worker)
        self.worker.start()

    def _use_pending(self):
        if self.busy:
            return
        doc = self.documents.get(self.selected, {})
        page = doc.get('pending', {}).pop(self.page_no, None)
        if page:
            doc['pages'][page.page_no] = page
            doc['plan'].pages[page.page_no - 1] = page
            doc['plan'].dirty = True
            doc['plan'].warnings = [w for w in doc['plan'].warnings if not (w.code == 'reocr_conflict' and w.page_no == page.page_no)]
            self._show_text()
            self._show_plan()

    def _keep_manual(self):
        if self.busy:
            return
        doc = self.documents.get(self.selected, {})
        if doc.get('pending', {}).pop(self.page_no, None):
            plan = doc['plan']
            plan.warnings = [w for w in plan.warnings if not (w.code == 'reocr_conflict' and w.page_no == self.page_no)]
            plan.dirty = True
            self._show_plan()
            self.status.set('Edits kept. Rebuild the plan to continue.')

    def _candidates(self):
        page = self._page()
        if not page:
            return
        window = tk.Toplevel(self.root)
        window.title('Recognition candidates')
        window.geometry('600x450')
        text = tk.Text(window, wrap='word')
        text.pack(fill='both', expand=True)
        for b in page.blocks:
            text.insert('end', f"{b.text}\nConfidence: {(b.confidence if b.confidence is not None else 'Native / edited text')}\n")
            for candidate in b.candidates:
                text.insert('end', f"Alternative: {candidate.get('text', '')}\n")
            text.insert('end', '\n')
        pending = self.documents.get(self.selected, {}).get('pending', {}).get(page.page_no)
        if pending:
            text.insert('end', 'New OCR result awaiting comparison:\n' + pending.text + '\n\n')
        text.insert('end', 'Confidence is a model signal, not an accuracy score.')
        text.configure(state='disabled', bg=self.colors['panel'], fg=self.colors['text'])

    def _show_plan(self):
        self.items.delete(*self.items.get_children())
        plan = self._plan()
        if not plan:
            return
        groups = {}
        for index, item in enumerate(plan.items):
            parent = ''
            for component in Path(item.chapter_dir_name).parts:
                key = (parent, component)
                if key not in groups:
                    node = f'group-{len(groups)}'
                    self.items.insert(parent, 'end', iid=node, text=component, open=True)
                    groups[key] = node
                parent = groups[key]
            self.items.insert(parent, 'end', iid=f'item-{index}', text=('Excluded · ' if item.excluded else '') + item.section_label + ' ' + item.section_title, values=(item.start_page, item.end_page, item.page_count))
        self.warnings.configure(state='normal')
        self.warnings.delete('1.0', 'end')
        if plan.dirty:
            self.warnings.insert('end', 'Text changed. Rebuild the plan before export.\n')
        for w in plan.warnings:
            self.warnings.insert('end', f'{w.severity}: {w.message}\n')
        if plan.omitted_pages:
            self.warnings.insert('end', f'Omitted pages: {plan.omitted_pages}\n')
        self.warnings.configure(state='disabled')

    def _selected_items(self):
        return [int(node[5:]) for node in self.items.selection() if node.startswith('item-')]

    def _edit_item(self, new=False):
        plan = self._plan()
        indices = self._selected_items()
        if not plan or self.busy or (not new and (not indices)):
            return
        original = plan.items[indices[0]] if not new else SplitItem('Manual', 'Manual split', 'Manual', 'Manual split', 1, plan.total_pages, 'Manual split', 'Manual split.pdf', manual=True)
        window = tk.Toplevel(self.root)
        window.title('Edit split item')
        window.transient(self.root)
        fields = {}
        for row, (key, label) in enumerate([('section_title', 'Title'), ('section_label', 'Label'), ('chapter_dir_name', 'Chapter folder'), ('start_page', 'Start page'), ('end_page', 'End page')]):
            ttk.Label(window, text=label).grid(row=row, column=0, padx=12, pady=8, sticky='w')
            var = tk.StringVar(value=str(getattr(original, key)))
            ttk.Entry(window, textvariable=var, width=35).grid(row=row, column=1, padx=12)
            fields[key] = var
        chapters = {f'{entry.title} (page {entry.page_index + 1})': entry for entry in plan.entries if entry.kind == 'chapter'}
        parent_name = tk.StringVar(value='Custom folder')
        ttk.Label(window, text='Parent chapter').grid(row=5, column=0, padx=12, pady=8, sticky='w')
        parent_box = ttk.Combobox(window, textvariable=parent_name, values=['Custom folder', *chapters], state='readonly', width=33)
        parent_box.grid(row=5, column=1, padx=12)

        def choose_parent(event=None):
            from .headings import parse_heading
            chapter = chapters.get(parent_name.get())
            if chapter:
                title = parse_heading(chapter.title)
                directory = sanitize_name(f'Chapter {chapter.display_label} - {(title.title if title else chapter.title)}')
                existing = next((i for i in plan.items if i.chapter_label == chapter.display_label and i.part_id == chapter.parent_id), None)
                fields['chapter_dir_name'].set(existing.chapter_dir_name if existing else directory)
        parent_box.bind('<<ComboboxSelected>>', choose_parent)

        def save():
            item = deepcopy(original)
            try:
                for key, var in fields.items():
                    setattr(item, key, int(var.get()) if key.endswith('_page') else var.get().strip())
                item.file_name = sanitize_name(item.section_label + ' ' + item.section_title) + '.pdf'
                item.manual = True
                candidate = deepcopy(plan)
                chapter = chapters.get(parent_name.get())
                if chapter:
                    from .headings import parse_heading
                    heading = parse_heading(chapter.title)
                    item.chapter_label = chapter.display_label
                    item.chapter_title = heading.title if heading else chapter.title
                    item.part_id = chapter.parent_id
                for entry in candidate.entries:
                    if entry.id in item.entry_ids and entry.kind == 'section':
                        if chapter:
                            entry.parent_id = chapter.id
                        entry.title = item.section_label + ' ' + item.section_title
                        entry.page_index = item.start_page - 1
                        entry.source = 'user'
                        entry.evidence.append('Manual plan correction')
                if new:
                    candidate.items.append(item)
                else:
                    candidate.items[indices[0]] = item
                validate_plan(candidate, verify_input=False)
                plan.items = candidate.items
                plan.entries = candidate.entries
                plan.omitted_pages = candidate.omitted_pages
                self.accept.set(False)
                self._show_plan()
                window.destroy()
            except ValueError as exc:
                messagebox.showerror('PDFSplitter', str(exc), parent=window)
        ttk.Button(window, text='Save', command=save).grid(row=6, column=1, pady=12)

    def _commit_items(self, candidate):
        if self.busy:
            return
        try:
            validate_plan(candidate, verify_input=False)
            plan = self._plan()
            plan.items = candidate.items
            plan.omitted_pages = candidate.omitted_pages
            self.accept.set(False)
            self._show_plan()
        except ValueError as exc:
            messagebox.showerror('PDFSplitter', str(exc), parent=self.root)

    def _exclude(self):
        plan = self._plan()
        if not plan:
            return
        plan = deepcopy(plan)
        for index in self._selected_items():
            plan.items[index].excluded = not plan.items[index].excluded
            plan.items[index].manual = True
        self._commit_items(plan)

    def _merge(self):
        plan = self._plan()
        indices = self._selected_items()
        if not plan or len(indices) < 2:
            return
        plan = deepcopy(plan)
        group = sorted([plan.items[i] for i in indices], key=lambda i: i.start_page)
        if any((a.end_page + 1 != b.start_page for a, b in zip(group, group[1:]))):
            messagebox.showerror('PDFSplitter', 'Select consecutive page ranges.')
            return
        first = group[0]
        first.end_page = group[-1].end_page
        first.section_title = ' + '.join((i.section_title for i in group))
        first.entry_ids = list(dict.fromkeys((e for i in group for e in i.entry_ids)))
        first.manual = True
        first.file_name = sanitize_name(first.section_label + ' ' + first.section_title) + '.pdf'
        for item in group[1:]:
            item.excluded = True
            item.manual = True
        self._commit_items(plan)

    def _split(self):
        plan = self._plan()
        indices = self._selected_items()
        if not plan or not indices:
            return
        plan = deepcopy(plan)
        item = plan.items[indices[0]]
        if item.start_page == item.end_page:
            return
        page = simpledialog.askinteger('Divide range', 'First page of the second output', minvalue=item.start_page + 1, maxvalue=item.end_page, parent=self.root)
        if page is None:
            return
        right = deepcopy(item)
        right.start_page = page
        right.manual = True
        right.section_title += ' (Part 2)'
        right.file_name = sanitize_name(right.section_label + ' ' + right.section_title) + '.pdf'
        item.end_page = page - 1
        item.manual = True
        plan.items.insert(indices[0] + 1, right)
        self._commit_items(plan)

    def _boundary(self):
        plan = self._plan()
        indices = self._selected_items()
        if plan and indices:
            self.page_no = plan.items[indices[0]].start_page
            self.workbook.select(self.ocr_tab)
            self._show_text()
            self._preview()

    def _rebuild(self):
        plan = self._plan()
        if not plan or self.busy:
            return
        try:
            rebuild_plan(plan)
            self._show_plan()
            self.status.set('Plan rebuilt. Manual edits preserved.')
        except ValueError as exc:
            messagebox.showerror('PDFSplitter', str(exc))

    def _save_plan(self):
        plan = self._plan()
        if not plan:
            return
        filename = filedialog.asksaveasfilename(title='Save split plan', defaultextension='.json', filetypes=[('JSON', '*.json')])
        if filename:
            if Path(filename).resolve() == Path(plan.input_pdf):
                messagebox.showerror('PDFSplitter', 'The plan cannot overwrite the input PDF.')
                return
            plan.save(Path(filename))
            self._log(f'Plan saved: {filename}')

    def _load_plan(self):
        filename = filedialog.askopenfilename(title='Load split plan', filetypes=[('JSON', '*.json')])
        if not filename:
            return
        try:
            plan = SplitPlan.load(Path(filename))
            validate_plan(plan)
            key = plan.input_pdf
            if key not in self.documents:
                node = f'doc-{len(self.documents)}'
                self.documents[key] = {'node': node, 'plan': None, 'pages': {}, 'state': 'Review required', 'pending': {}}
                self.files.insert('', 'end', iid=node, text=Path(key).name, open=True)
                self.node_map[node] = (key, 1)
            for page in plan.pages:
                self.queue.put(('event', key, {'stage': 'page', 'page': page, 'total': plan.total_pages}))
            self.queue.put(('plan', key, plan))
        except Exception as exc:
            messagebox.showerror('PDFSplitter', str(exc))

    def _choose_output(self):
        path = filedialog.askdirectory(title='Choose output parent')
        if path:
            self.output.set(path)

    def _export(self):
        if self.busy:
            return
        plan = self._plan()
        if not plan:
            return
        key = self.selected
        root = Path(self.output.get()) if self.output.get() else Path(key).parent
        target = root / default_output_dir(Path(key)).name
        self.busy = True
        self.cancel.clear()
        accepted = self.accept.get()
        snapshot = deepcopy(plan)
        self.queue.put(('state', key, 'Exporting'))

        def worker():
            try:
                result = export_plan(snapshot, target, accept_warnings=accepted, unique_output=True, cancel_token=self.cancel, progress_callback=lambda e: self.queue.put(('log', f"Exporting {e['done']}/{e['total']}")))
                self.queue.put(('exported', key, result))
            except CancelledError:
                self.queue.put(('state', key, 'Cancelled'))
            except Exception as exc:
                self.queue.put(('state', key, 'Review required'))
                self.queue.put(('log', str(exc)))
            finally:
                self.queue.put(('finished',))
        self.worker = threading.Thread(target=worker)
        self.worker.start()

    def _clear_cache(self):
        if self.busy:
            return
        try:
            clear_cache()
            self._log('Cache cleared.')
        except OSError as exc:
            messagebox.showerror('PDFSplitter', str(exc))

    def _cancel(self):
        if self.busy:
            self.cancel.set()
            self.status.set('Cancelling...')

    def _close(self):
        self.cancel.set()
        self.shutdown.set()
        self.root.withdraw()

        def finish():
            if self.worker and self.worker.is_alive():
                self.root.after(100, finish)
            else:
                self.root.destroy()
        finish()

    def _open_last_output(self):
        if self.last_output_dir:
            subprocess.run(['open', str(self.last_output_dir)], check=False)

    def run(self):
        self.root.mainloop()

def launch_gui():
    PDFSplitterApp().run()
