from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from .splitter import split_pdf


@dataclass(frozen=True)
class JobMessage:
    kind: str
    text: str
    output_dir: Path | None = None


def default_output_dir(input_pdf: Path) -> Path:
    safe_stem = input_pdf.stem.strip() or "book"
    return input_pdf.parent / f"{safe_stem} - split"


class PDFSplitterApp:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title("PDFSplitter")
        self.root.geometry("760x560")
        self.root.minsize(680, 500)

        self.message_queue: queue.Queue[JobMessage] = queue.Queue()
        self.last_output_dir: Path | None = None
        self.worker_running = False

        self.source_var = tk.StringVar(value="auto")
        self.include_intro_var = tk.BooleanVar(value=True)
        self.section_depth_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(
            value="Drop one or more PDF files here, or click “Choose PDFs”."
        )

        self._build_ui()
        self.root.after(150, self._poll_messages)

    def _build_ui(self) -> None:
        self.root.configure(bg="#f4f1ea")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(
            outer,
            text="PDFSplitter",
            font=("Helvetica Neue", 22, "bold"),
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            outer,
            text="Drag a PDF into the window and it will be split automatically.",
            font=("Helvetica Neue", 11),
        )
        subtitle.pack(anchor="w", pady=(4, 16))

        controls = ttk.Frame(outer)
        controls.pack(fill="x")

        ttk.Label(controls, text="Detection:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        source_menu = ttk.Combobox(
            controls,
            textvariable=self.source_var,
            values=("auto", "outline", "toc", "scan"),
            state="readonly",
            width=10,
        )
        source_menu.grid(row=0, column=1, sticky="w")

        ttk.Label(controls, text="Section Depth:").grid(row=0, column=2, sticky="w", padx=(20, 8))
        section_entry = ttk.Entry(controls, textvariable=self.section_depth_var, width=8)
        section_entry.grid(row=0, column=3, sticky="w")

        intro_check = ttk.Checkbutton(
            controls,
            text="Include chapter intro PDFs",
            variable=self.include_intro_var,
        )
        intro_check.grid(row=0, column=4, sticky="w", padx=(20, 0))

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(14, 14))

        choose_button = ttk.Button(button_row, text="Choose PDFs", command=self._choose_files)
        choose_button.pack(side="left")

        open_button = ttk.Button(
            button_row,
            text="Open Last Output Folder",
            command=self._open_last_output,
        )
        open_button.pack(side="left", padx=(10, 0))

        hint = ttk.Label(
            outer,
            text="Default output: next to the input PDF, in a folder named “<file> - split”.",
            font=("Helvetica Neue", 10),
        )
        hint.pack(anchor="w", pady=(0, 12))

        drop_frame = tk.Frame(
            outer,
            bg="#fffaf0",
            highlightbackground="#c56a2d",
            highlightthickness=2,
            bd=0,
        )
        drop_frame.pack(fill="x", pady=(0, 14))
        drop_frame.drop_target_register(DND_FILES)
        drop_frame.dnd_bind("<<Drop>>", self._on_drop)

        drop_label = tk.Label(
            drop_frame,
            text="Drop PDF files here",
            bg="#fffaf0",
            fg="#7a3f14",
            font=("Helvetica Neue", 18, "bold"),
            pady=28,
        )
        drop_label.pack(fill="both", expand=True)
        drop_label.drop_target_register(DND_FILES)
        drop_label.dnd_bind("<<Drop>>", self._on_drop)

        status = ttk.Label(
            outer,
            textvariable=self.status_var,
            font=("Helvetica Neue", 10),
        )
        status.pack(anchor="w", pady=(0, 8))

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            height=16,
            bg="#fffdf8",
            fg="#2f241d",
            relief="solid",
            borderwidth=1,
            font=("SF Mono", 11),
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.configure(state="disabled")

        self._log("Ready.")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_log(f"[{timestamp}] {text}")

    def _choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose PDF files",
            filetypes=[("PDF files", "*.pdf")],
        )
        if paths:
            self._start_jobs([Path(path) for path in paths])

    def _parse_drop_paths(self, data: str) -> list[Path]:
        raw_paths = self.root.tk.splitlist(data)
        paths: list[Path] = []
        for raw_path in raw_paths:
            cleaned = raw_path.strip()
            if cleaned.startswith("{") and cleaned.endswith("}"):
                cleaned = cleaned[1:-1]
            path = Path(cleaned).expanduser()
            if path.suffix.lower() == ".pdf" and path.exists():
                paths.append(path)
        return paths

    def _on_drop(self, event: tk.Event) -> None:
        paths = self._parse_drop_paths(str(event.data))
        if not paths:
            messagebox.showerror("PDFSplitter", "No valid PDF files were dropped.")
            return
        self._start_jobs(paths)

    def _start_jobs(self, paths: list[Path]) -> None:
        if self.worker_running:
            messagebox.showinfo("PDFSplitter", "A split job is already running. Please wait.")
            return

        section_depth = self._read_section_depth()
        if section_depth is False:
            return

        self.worker_running = True
        self.status_var.set(f"Splitting {len(paths)} PDF file(s)...")
        self._log(f"Queued {len(paths)} file(s).")
        source = self.source_var.get()
        include_chapter_intro = self.include_intro_var.get()
        worker = threading.Thread(
            target=self._worker,
            args=(paths, section_depth, source, include_chapter_intro),
            daemon=True,
        )
        worker.start()

    def _read_section_depth(self) -> int | None | bool:
        raw = self.section_depth_var.get().strip()
        if not raw:
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        messagebox.showerror("PDFSplitter", "Section Depth must be a positive integer.")
        return False

    def _worker(
        self,
        paths: list[Path],
        section_depth: int | None,
        source: str,
        include_chapter_intro: bool,
    ) -> None:
        for path in paths:
            output_dir = default_output_dir(path)
            self.message_queue.put(JobMessage("log", f"Starting: {path}"))
            try:
                result = split_pdf(
                    input_pdf=path,
                    output_dir=output_dir,
                    source=source,
                    include_chapter_intro=include_chapter_intro,
                    max_section_depth=section_depth,
                )
            except Exception as exc:
                self.message_queue.put(JobMessage("error", f"{path.name}: {exc}"))
                continue

            self.message_queue.put(
                JobMessage(
                    "success",
                    f"{path.name}: created {result['split_count']} PDFs in {output_dir}",
                    output_dir=output_dir,
                )
            )
        self.message_queue.put(JobMessage("done", "All jobs finished."))

    def _poll_messages(self) -> None:
        while True:
            try:
                message = self.message_queue.get_nowait()
            except queue.Empty:
                break

            if message.kind == "log":
                self._log(message.text)
            elif message.kind == "success":
                self.last_output_dir = message.output_dir
                self._log(message.text)
            elif message.kind == "error":
                self._log(f"Error: {message.text}")
            elif message.kind == "done":
                self.worker_running = False
                self.status_var.set("Done. Drop more PDFs or choose files to run again.")
                self._log(message.text)

        self.root.after(150, self._poll_messages)

    def _open_last_output(self) -> None:
        if self.last_output_dir is None or not self.last_output_dir.exists():
            messagebox.showinfo("PDFSplitter", "No output folder is available yet.")
            return
        subprocess.run(["open", str(self.last_output_dir)], check=False)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    app = PDFSplitterApp()
    app.run()
