from __future__ import annotations

"""Tk desktop application for running extraction tasks interactively."""

from datetime import datetime
from functools import partial
import os
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from core import (
    DeleteRequest,
    DeleteResult,
    DeepProbeDecision,
    EmbeddedExtractionResult,
    ProcessLogEntry,
    ExtractTaskResult,
    ExtractedRootDecisionRequest,
    extract_task,
)
from core.workspace import build_task_plan
from .dragdrop import WindowsFileDrop
from .file_dialogs import pick_directory
from .session_log import SessionLogWriter
from .settings import (
    UiSettings,
    build_extract_options_from_settings,
    collect_passwords_from_text,
    default_ui_settings,
    load_ui_settings,
    save_ui_settings,
    sync_bool_state,
)
from .tasks import TaskItem, make_task_items, summarize_tasks


class DesktopExtractorApp:
    """Main desktop window, task list, settings, and execution loop."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ArcWeaver")
        self.root.geometry("1120x760")
        self.root.minsize(980, 680)

        self._tasks: list[TaskItem] = []
        self._event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._run_thread: threading.Thread | None = None
        self._run_total = 0
        self._run_done = 0
        self._run_warnings: list[str] = []
        self._active_run_settings: UiSettings | None = None
        self._current_decision_event: threading.Event | None = None
        self._current_decision_value: DeepProbeDecision | None = None
        self._defaults = default_ui_settings()
        self.verbose_log_var = tk.BooleanVar(value=True)

        self._settings_path = self._resolve_settings_path()
        self._session_log_path = self._settings_path.parent / "desktop_gui_session.log"

        self._setup_style()
        self._build_ui()
        self._logger = SessionLogWriter(self.log, self._session_log_path)
        self._bind_drag_drop()
        self._load_settings()
        self._poll_events()

    def _resolve_settings_path(self) -> Path:
        """Resolve the persisted settings path under the user's profile."""

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / "ArcWeaver" if appdata else (Path.home() / ".arcweaver")
        base.mkdir(parents=True, exist_ok=True)
        return base / "gui_settings.json"

    def _setup_style(self) -> None:
        """Configure the desktop theme and shared widget colors."""

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.configure(bg="#eef2f6")
        style.configure("TFrame", background="#eef2f6")
        style.configure("Card.TLabelframe", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#0f172a")
        style.configure("TLabel", background="#eef2f6", foreground="#0f172a")
        style.configure("TButton", padding=(5, 1))
        style.configure("TCheckbutton", padding=(0, 1))
        style.configure("TRadiobutton", padding=(0, 1))
        style.configure("Primary.TButton", background="#1d4ed8", foreground="#ffffff")
        style.configure("Hint.TLabel", background="#eef2f6", foreground="#475569")
        style.configure("Value.TLabel", background="#eef2f6", foreground="#0f172a")

    def _build_ui(self) -> None:
        """Create the full window layout."""

        wrap = ttk.Frame(self.root, padding=8)
        wrap.pack(fill=BOTH, expand=True)

        self._build_input_card(wrap)
        self._build_task_card(wrap)
        self._build_runtime_card(wrap)
        self._build_action_card(wrap)
        self._build_log_card(wrap)

    def _build_input_card(self, parent: ttk.Frame) -> None:
        """Build the task input area for file and directory tasks."""

        card = ttk.LabelFrame(parent, text="任务输入", style="Card.TLabelframe", padding=8)
        card.pack(fill=X, pady=(0, 6))

        self.mode_var = tk.StringVar(value="single")
        self.single_path_var = tk.StringVar()
        self.multi_root_var = tk.StringVar()
        self.drop_hint = tk.StringVar()

        row = ttk.Frame(card)
        row.pack(fill=X)
        ttk.Radiobutton(
            row,
            text="单文件",
            variable=self.mode_var,
            value="single",
            command=self._on_mode_change,
        ).pack(side=LEFT, padx=(0, 10))
        ttk.Radiobutton(
            row,
            text="目录任务",
            variable=self.mode_var,
            value="multi",
            command=self._on_mode_change,
        ).pack(side=LEFT)

        self.single_row = ttk.Frame(card)
        self.single_row.pack(fill=X, pady=(5, 0))
        ttk.Entry(self.single_row, textvariable=self.single_path_var).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(
            self.single_row,
            text="选择文件",
            style="Primary.TButton",
            command=self._pick_single_files,
        ).pack(side=RIGHT, padx=(8, 0))

        self.multi_row = ttk.Frame(card)
        ttk.Label(self.multi_row, text="工作目录").pack(side=LEFT)
        ttk.Entry(self.multi_row, textvariable=self.multi_root_var).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(8, 0),
        )
        ttk.Button(
            self.multi_row,
            text="选择目录",
            style="Primary.TButton",
            command=self._pick_directory_task,
        ).pack(side=LEFT, padx=(8, 0))

        ttk.Label(card, textvariable=self.drop_hint, style="Hint.TLabel").pack(anchor="w", pady=(5, 0))
        self._on_mode_change()

    def _build_task_card(self, parent: ttk.Frame) -> None:
        """Build the task table and task selection controls."""

        card = ttk.LabelFrame(parent, text="任务列表", style="Card.TLabelframe", padding=8)
        card.pack(fill=BOTH, expand=True, pady=(0, 6))

        top = ttk.Frame(card)
        top.pack(fill=X, pady=(0, 5))
        ttk.Button(top, text="清空", command=self._clear_tasks).pack(side=LEFT)
        self.task_stats = tk.StringVar(value="任务 0")
        ttk.Label(top, textvariable=self.task_stats, style="Hint.TLabel").pack(side=RIGHT)

        tree_wrap = ttk.Frame(card)
        tree_wrap.pack(fill=BOTH, expand=True)
        self.task_tree = ttk.Treeview(
            tree_wrap,
            columns=("on", "type", "path"),
            show="headings",
            height=4,
        )
        self.task_tree.heading("on", text="参与")
        self.task_tree.heading("type", text="类型")
        self.task_tree.heading("path", text="任务标识")
        self.task_tree.column("on", width=60, anchor="center")
        self.task_tree.column("type", width=60, anchor="center")
        self.task_tree.column("path", width=980)
        self.task_tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.task_tree.bind("<Double-1>", self._toggle_task)

        scrollbar = tk.Scrollbar(tree_wrap, orient="vertical", command=self.task_tree.yview, width=14)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.task_tree.configure(yscrollcommand=scrollbar.set)

    def _build_runtime_card(self, parent: ttk.Frame) -> None:
        """Build runtime settings, cleanup options, and password input."""

        card = ttk.LabelFrame(parent, text="运行设置", style="Card.TLabelframe", padding=8)
        card.pack(fill=X, pady=(0, 6))

        self.keep_source_var = tk.BooleanVar(value=self._defaults.keep_source)
        self.detect_polyglot_var = tk.BooleanVar(value=self._defaults.detect_polyglot)
        self.cleanup_var = tk.BooleanVar(value=self._defaults.cleanup)
        self.promote_output_var = tk.BooleanVar(value=self._defaults.promote_output)
        self.recycle_var = tk.BooleanVar(value=self._defaults.recycle)
        self.prompt_large_root_var = tk.BooleanVar(value=self._defaults.prompt_large_extracted_root)
        self.large_root_file_threshold_var = tk.IntVar(value=self._defaults.large_root_file_threshold)
        self.large_root_dir_threshold_var = tk.IntVar(value=self._defaults.large_root_dir_threshold)
        self.large_root_preview_limit_var = tk.IntVar(value=self._defaults.large_root_preview_limit)
        self.large_root_threshold_mode_var = tk.StringVar(
            value="并且" if self._defaults.large_root_threshold_mode == "and" else "或者"
        )

        self.keep_source_state = tk.StringVar()
        self.detect_polyglot_state = tk.StringVar()
        self.cleanup_state = tk.StringVar()
        self.promote_output_state = tk.StringVar()
        self.recycle_state = tk.StringVar()
        self.prompt_large_root_state = tk.StringVar()

        row = ttk.Frame(card)
        row.pack(fill=X)
        ttk.Checkbutton(row, text="保留源压缩包", variable=self.keep_source_var).pack(side=LEFT)
        ttk.Label(row, textvariable=self.keep_source_state, style="Value.TLabel").pack(side=LEFT, padx=(4, 10))
        ttk.Checkbutton(row, text="检测 Polyglot", variable=self.detect_polyglot_var).pack(side=LEFT, padx=(10, 0))
        ttk.Label(row, textvariable=self.detect_polyglot_state, style="Value.TLabel").pack(side=LEFT, padx=(4, 10))
        ttk.Checkbutton(row, text="完成后清理工作目录", variable=self.cleanup_var).pack(side=LEFT, padx=(10, 0))
        ttk.Label(row, textvariable=self.cleanup_state, style="Value.TLabel").pack(side=LEFT, padx=(4, 10))
        ttk.Checkbutton(row, text="提取结果到工作目录", variable=self.promote_output_var).pack(side=LEFT, padx=(10, 0))
        ttk.Label(row, textvariable=self.promote_output_state, style="Value.TLabel").pack(side=LEFT, padx=(4, 10))
        ttk.Checkbutton(row, text="使用系统回收站", variable=self.recycle_var).pack(side=LEFT, padx=(10, 0))
        ttk.Label(row, textvariable=self.recycle_state, style="Value.TLabel").pack(side=LEFT, padx=(4, 0))

        row2 = ttk.Frame(card)
        row2.pack(fill=X, pady=(4, 0))
        ttk.Checkbutton(row2, text="手动确认大目录", variable=self.prompt_large_root_var).pack(side=LEFT)
        ttk.Label(row2, textvariable=self.prompt_large_root_state, style="Value.TLabel").pack(side=LEFT, padx=(4, 8))
        ttk.Label(row2, text="当文件数量超过").pack(side=LEFT)
        ttk.Spinbox(row2, from_=1, to=1000000, width=5, textvariable=self.large_root_file_threshold_var).pack(side=LEFT, padx=(4, 4))
        threshold_mode = ttk.Combobox(
            row2,
            width=4,
            state="readonly",
            values=("并且", "或者"),
            textvariable=self.large_root_threshold_mode_var,
        )
        threshold_mode.pack(side=LEFT, padx=(0, 6))
        ttk.Label(row2, text="目录数量超过").pack(side=LEFT)
        ttk.Spinbox(row2, from_=1, to=1000000, width=5, textvariable=self.large_root_dir_threshold_var).pack(side=LEFT, padx=(4, 4))
        ttk.Label(row2, text="时，手动确认是否继续探测，避免解压出来的非归档文件过多仍旧深度探测导致耗时过久").pack(side=LEFT)

        sync_bool_state(self.keep_source_var, self.keep_source_state)
        sync_bool_state(self.detect_polyglot_var, self.detect_polyglot_state)
        sync_bool_state(self.cleanup_var, self.cleanup_state)
        sync_bool_state(self.promote_output_var, self.promote_output_state)
        sync_bool_state(self.recycle_var, self.recycle_state)
        sync_bool_state(self.prompt_large_root_var, self.prompt_large_root_state)

        pwd = ttk.Frame(card)
        pwd.pack(fill=X, pady=(4, 0))
        ttk.Label(pwd, text="密码词典", width=12).pack(side=LEFT, anchor="n")
        pwd_text_wrap = ttk.Frame(pwd)
        pwd_text_wrap.pack(side=LEFT, fill=X, expand=True)
        self.password_text = ScrolledText(pwd_text_wrap, height=3)
        self.password_text.pack(fill=X, expand=True)
        ttk.Label(
            card,
            text="每行一个密码，会自动去除首尾空白并去重。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(6, 0))

    def _build_action_card(self, parent: ttk.Frame) -> None:
        """Build the run button, save button, and progress row."""

        row = ttk.Frame(parent)
        row.pack(fill=X, pady=(0, 4))
        self.run_btn = ttk.Button(row, text="开始解压", style="Primary.TButton", command=self._start_run)
        self.run_btn.pack(side=LEFT)
        ttk.Button(row, text="保存设置", command=self._save_settings).pack(side=LEFT, padx=(8, 0))
        self.status = tk.StringVar(value="就绪")
        ttk.Label(row, textvariable=self.status).pack(side=RIGHT)

        progress_row = ttk.Frame(parent)
        progress_row.pack(fill=X, pady=(0, 4))
        self.progress_text = tk.StringVar(value="进度：0/0")
        ttk.Label(progress_row, textvariable=self.progress_text).pack(side=LEFT)
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=1, value=0)
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(10, 0))

    def _build_log_card(self, parent: ttk.Frame) -> None:
        """Build the scrolling execution log panel."""

        card = ttk.LabelFrame(parent, text="执行日志", style="Card.TLabelframe", padding=8)
        card.pack(fill=BOTH, expand=True)

        toolbar = ttk.Frame(card)
        toolbar.pack(fill=X, pady=(0, 4))
        ttk.Checkbutton(toolbar, text="详细日志", variable=self.verbose_log_var).pack(side=LEFT)
        ttk.Button(toolbar, text="清空日志", command=self._clear_log).pack(side=RIGHT)

        self.log = ScrolledText(card, height=12)
        self.log.pack(fill=BOTH, expand=True)

    def _bind_drag_drop(self) -> None:
        """Enable native drag-and-drop on Windows when available."""

        if os.name != "nt":
            self._drop = None
            return
        try:
            self._drop = WindowsFileDrop(self.root, self._on_drop)
        except Exception:
            self._drop = None

    def _on_drop(self, paths: list[str]) -> None:
        """Handle files or directories dropped onto the desktop window."""

        if not paths:
            return

        absolute_paths = [os.path.abspath(path) for path in paths]
        if self.mode_var.get() == "single":
            file_paths = [path for path in absolute_paths if os.path.isfile(path)]
            if not file_paths:
                messagebox.showwarning("提示", "当前为单文件模式，只能拖入文件。")
                return
            self._append_tasks(file_paths, expected_kind="file")
            self.single_path_var.set(f"已加入 {len(file_paths)} 个文件")
            return

        dir_paths = [path for path in absolute_paths if os.path.isdir(path)]
        if not dir_paths:
            messagebox.showwarning("提示", "当前为目录任务模式，只能拖入目录。")
            return
        self._append_tasks(dir_paths, expected_kind="dir")
        self.multi_root_var.set(f"已加入 {len(dir_paths)} 个目录")

    def _on_mode_change(self) -> None:
        """Switch visible input controls when the task mode changes."""

        if self.mode_var.get() == "single":
            self.single_row.pack(fill=X, pady=(5, 0))
            self.multi_row.pack_forget()
            self.drop_hint.set("支持拖拽：单文件模式只接收文件。")
        else:
            self.multi_row.pack(fill=X, pady=(5, 0))
            self.single_row.pack_forget()
            self.drop_hint.set("支持拖拽：目录任务模式只接收目录，目录选择为单选。")

    def _pick_single_files(self) -> None:
        """Open the native file picker for single-file task mode."""

        paths = list(filedialog.askopenfilenames())
        if not paths:
            return
        file_paths = [os.path.abspath(path) for path in paths if os.path.isfile(path)]
        if not file_paths:
            messagebox.showwarning("提示", "未选择有效文件。")
            return
        self._append_tasks(file_paths, expected_kind="file")
        self.single_path_var.set(f"已加入 {len(file_paths)} 个文件")

    def _pick_directory_task(self) -> None:
        """Open the native directory picker for directory task mode."""

        selected_dir = pick_directory(self.root, self.multi_root_var.get())
        if not selected_dir:
            return
        dir_path = os.path.abspath(selected_dir)
        if not os.path.isdir(dir_path):
            messagebox.showwarning("提示", "未选择有效目录。")
            return
        self._append_tasks([dir_path], expected_kind="dir")
        self.multi_root_var.set("已加入 1 个目录")
        self._log("已加入 1 个目录任务")

    def _append_tasks(self, paths: list[str], expected_kind: str) -> None:
        """Add newly selected paths into the task table."""

        existing_ids = {task.task_id for task in self._tasks}
        new_tasks = make_task_items(paths, expected_kind, existing_ids)
        if not new_tasks:
            messagebox.showinfo("提示", "没有新增任务，可能已在任务列表中。")
            return
        self._tasks.extend(new_tasks)
        self._refresh_tasks()

    def _refresh_tasks(self) -> None:
        """Refresh the task table rows and summary text."""

        for item_id in self.task_tree.get_children():
            self.task_tree.delete(item_id)

        for task in self._tasks:
            kind_text = "文件" if task.kind == "file" else "目录"
            self.task_tree.insert(
                "",
                END,
                iid=task.task_id,
                values=(
                    "是" if task.selected else "否",
                    kind_text,
                    task.path,
                ),
            )
        self.task_stats.set(summarize_tasks(self._tasks))

    def _toggle_task(self, _event) -> None:
        """Toggle the selected flag for the currently highlighted task row."""

        selection = self.task_tree.selection()
        if not selection:
            return
        task_id = selection[0]
        for task in self._tasks:
            if task.task_id == task_id:
                task.selected = not task.selected
                break
        self._refresh_tasks()

    def _clear_tasks(self) -> None:
        self._tasks.clear()
        self.single_path_var.set("")
        self.multi_root_var.set("")
        self._refresh_tasks()

    def _start_run(self) -> None:
        """Validate the current selection and start the worker thread."""

        if self._run_thread and self._run_thread.is_alive():
            messagebox.showinfo("提示", "当前已有任务正在执行。")
            return

        selected = [task for task in self._tasks if task.selected]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个任务。")
            return

        if self.verbose_log_var.get():
            self._log(f"开始执行，任务数={len(selected)}")
            for index, task in enumerate(selected, start=1):
                self._log(f"  任务[{index}] kind={task.kind} path={task.path}")

        self._run_total = len(selected)
        self._run_done = 0
        self._run_warnings = []
        self._active_run_settings = self._collect_current_settings()
        self.progress.configure(mode="determinate", maximum=max(1, self._run_total), value=0)
        self.progress_text.set(f"进度：0/{self._run_total}")
        self.status.set("执行中")
        self.run_btn.configure(state=tk.DISABLED)

        run_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self._run_thread = threading.Thread(
            target=self._run_worker,
            args=(selected, run_id, self._active_run_settings),
            daemon=True,
        )
        self._run_thread.start()

    def _run_worker(
        self,
        tasks: list[TaskItem],
        run_id: str,
        run_settings: UiSettings,
    ) -> None:
        """Run selected tasks in a background thread and post UI events."""

        try:
            for index, task in enumerate(tasks, start=1):
                options = build_extract_options_from_settings(run_settings)
                options.live_process_log_handler = self._emit_live_process_log
                options.extracted_root_decision_handler = self._request_large_root_decision
                plan = build_task_plan(task.path, options)
                self._event_queue.put(("log", f"[{index}/{len(tasks)}] {task.path}"))
                self._event_queue.put((
                    "debug_log",
                    (
                        "  配置: "
                        f"polyglot={options.detect_polyglot_archives} "
                        f"删除源文件={options.delete_source_archives} "
                        f"删除工作目录={options.delete_working_dir} "
                        f"提取结果到工作目录={options.promote_output_contents_to_workspace} "
                        f"系统回收站={options.use_recycle_bin} "
                        f"working_dir={plan.working_dir}"
                    ),
                ))
                try:
                    task_result = extract_task(task.path, options)
                except Exception:
                    error_text = traceback.format_exc()
                    task_result = ExtractTaskResult(
                        plan=plan,
                        extraction=EmbeddedExtractionResult(
                            output_dir=plan.output_dir,
                            working_dir=plan.working_dir,
                            status="failed",
                            next_action="inspect_errors",
                            scanned_files=[task.path],
                            errors=[error_text],
                        ),
                        cleanup=DeleteResult(),
                        delete_request=DeleteRequest(),
                    )
                self._event_queue.put(("task_done", (task, task_result, run_settings, run_id)))
        except Exception:
            self._event_queue.put(("run_error", traceback.format_exc()))
        finally:
            self._event_queue.put(("run_done", None))

    def _passwords(self) -> list[str]:
        """Read the password editor and return the normalized password list."""

        return collect_passwords_from_text(self.password_text.get("1.0", END))

    def _collect_current_settings(self) -> UiSettings:
        """Snapshot the current checkbox and password state."""

        return UiSettings(
            mode=self.mode_var.get(),
            single_path=self.single_path_var.get().strip(),
            multi_root=self.multi_root_var.get().strip(),
            keep_source=self.keep_source_var.get(),
            detect_polyglot=self.detect_polyglot_var.get(),
            cleanup=self.cleanup_var.get(),
            promote_output=self.promote_output_var.get(),
            recycle=self.recycle_var.get(),
            prompt_large_extracted_root=self.prompt_large_root_var.get(),
            large_root_file_threshold=self.large_root_file_threshold_var.get(),
            large_root_dir_threshold=self.large_root_dir_threshold_var.get(),
            large_root_preview_limit=self.large_root_preview_limit_var.get(),
            large_root_threshold_mode=(
                "and"
                if self.large_root_threshold_mode_var.get() == "并且"
                else "or"
            ),
            passwords=self._passwords(),
        )

    @staticmethod
    def _is_same_or_parent(path: str, target: str) -> bool:
        path_abs = os.path.abspath(path)
        target_abs = os.path.abspath(target)
        return path_abs == target_abs or target_abs.startswith(path_abs + os.sep)

    def _split_removed_paths(
        self,
        task_result: ExtractTaskResult,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """Bucket removed paths for clearer post-run logging."""

        removed_paths = [os.path.abspath(path) for path in task_result.cleanup.removed_paths]
        source_paths = [os.path.abspath(path) for path in task_result.delete_request.source_paths]
        working_dirs = [os.path.abspath(path) for path in task_result.delete_request.working_dirs]
        output_dir = os.path.abspath(task_result.plan.output_dir)

        source_related: list[str] = []
        working_related: list[str] = []
        promoted_output_dirs: list[str] = []
        other_removed: list[str] = []

        for removed_path in removed_paths:
            if removed_path == output_dir:
                promoted_output_dirs.append(removed_path)
                continue
            if any(self._is_same_or_parent(removed_path, working_dir) for working_dir in working_dirs):
                working_related.append(removed_path)
                continue
            if any(self._is_same_or_parent(removed_path, source_path) for source_path in source_paths):
                source_related.append(removed_path)
                continue
            other_removed.append(removed_path)

        return source_related, working_related, promoted_output_dirs, other_removed

    def _poll_events(self) -> None:
        """Process background worker events and update the UI."""

        try:
            while True:
                event_name, payload = self._event_queue.get_nowait()
                if event_name == "task_done":
                    task, task_result, run_settings, _run_id = payload  # type: ignore[misc]
                    result = task_result.extraction
                    self._log(
                        f"任务完成: {task.path} status={result.status} "
                        f"extracted={len(result.extracted_files)} next={result.next_action}"
                    )

                    if result.errors:
                        for error in result.errors:
                            self._log(f"  - {error}")

                    cleanup_result = task_result.cleanup
                    source_removed, working_removed, promoted_output_dirs, other_removed = self._split_removed_paths(task_result)
                    action_name = "移入 Windows 回收站" if run_settings.recycle else "删除"
                    if source_removed:
                        self._log(f"  - 源文件处理完成: {len(source_removed)} 项（{action_name}）")
                    if working_removed:
                        self._log(f"  - 工作目录清理完成: {len(working_removed)} 项")
                    if promoted_output_dirs:
                        self._log(f"  - 已收起中间 unzipped 目录: {len(promoted_output_dirs)} 项")
                    if other_removed:
                        self._log(f"  - 其他后处理移除: {len(other_removed)} 项")
                    if cleanup_result.moved_paths:
                        self._log(f"  - 已提取到工作目录: {len(cleanup_result.moved_paths)} 项")
                    if cleanup_result.skipped_paths:
                        self._log(f"  - 已跳过不存在项: {len(cleanup_result.skipped_paths)} 项")
                    for cleanup_message in cleanup_result.messages:
                        self._log(f"  - {cleanup_message}")

                    if result.status != "success":
                        self._run_warnings.append(f"{task.display_name}: {result.next_action}")

                    self._run_done += 1
                    self.progress.configure(value=self._run_done)
                    self.progress_text.set(f"进度：{self._run_done}/{self._run_total}")

                elif event_name == "run_done":
                    self._active_run_settings = None
                    self.run_btn.configure(state=tk.NORMAL)
                    if self._run_warnings:
                        self.status.set("执行完成（有异常）")
                        warning_preview = self._run_warnings[0]
                        messagebox.showwarning(
                            "执行完成（有异常）",
                            (
                                f"全部任务已执行完成，但存在 {len(self._run_warnings)} 条异常。\n\n"
                                f"首条异常：\n{warning_preview}\n\n"
                                "请查看执行日志中的详细信息。"
                            ),
                        )
                    else:
                        self.status.set("就绪")
                        messagebox.showinfo("完成", "全部任务执行完成")

                elif event_name == "run_error":
                    self._active_run_settings = None
                    self.status.set("执行失败")
                    self.run_btn.configure(state=tk.NORMAL)
                    self._log(str(payload))

                elif event_name == "debug_log":
                    if self.verbose_log_var.get():
                        self._log(str(payload))

                elif event_name == "log":
                    message = str(payload)
                    if self.verbose_log_var.get() or self._should_show_live_log(message):
                        self._log(message)
                elif event_name == "decision_request":
                    request = payload
                    self._handle_large_root_decision_request(request)
                elif event_name == "process_log":
                    entry = payload
                    if self.verbose_log_var.get() or self._is_visible_process_log_level(entry.level, "WARNING"):
                        self._log(f"  {entry.message}")
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._poll_events)

    def _log(self, message: str) -> None:
        """Write one line into the live session log."""

        self._logger.write(message)

    def _clear_log(self) -> None:
        """Clear the current live log panel."""

        self._logger.clear()

    @staticmethod
    def _is_visible_process_log_level(level: str, min_level: str) -> bool:
        """Return whether one log level should be visible in the current mode."""

        order = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }
        return order.get(level.upper(), 20) >= order.get(min_level.upper(), 20)

    def _should_show_live_log(self, message: str) -> bool:
        """Keep only high-level live log lines when verbose mode is disabled."""

        stripped = message.strip()
        if not stripped:
            return False
        return (
            stripped.startswith("开始执行")
            or stripped.startswith("任务[")
            or stripped.startswith("[")
            or stripped.startswith("任务完成:")
            or stripped.startswith("-")
        )

    def _load_settings(self) -> None:
        """Load persisted settings into the current UI state."""

        settings = load_ui_settings(self._settings_path)
        self.mode_var.set(settings.mode)
        self.single_path_var.set(settings.single_path)
        self.multi_root_var.set(settings.multi_root)
        self.keep_source_var.set(settings.keep_source)
        self.detect_polyglot_var.set(settings.detect_polyglot)
        self.cleanup_var.set(settings.cleanup)
        self.promote_output_var.set(settings.promote_output)
        self.recycle_var.set(settings.recycle)
        self.prompt_large_root_var.set(settings.prompt_large_extracted_root)
        self.large_root_file_threshold_var.set(settings.large_root_file_threshold)
        self.large_root_dir_threshold_var.set(settings.large_root_dir_threshold)
        self.large_root_preview_limit_var.set(settings.large_root_preview_limit)
        self.large_root_threshold_mode_var.set(
            "并且" if settings.large_root_threshold_mode == "and" else "或者"
        )
        self.password_text.delete("1.0", END)
        self.password_text.insert("1.0", "\n".join(settings.passwords))
        self._on_mode_change()

    def _save_settings(self) -> None:
        """Persist the current UI state to disk."""

        save_ui_settings(self._settings_path, self._collect_current_settings())
        self._log("设置已保存")

    def _request_large_root_decision(
        self,
        request: ExtractedRootDecisionRequest,
    ) -> DeepProbeDecision:
        """Block the worker until the UI answers a large-root prompt."""

        decision_event = threading.Event()
        self._current_decision_value = None
        self._current_decision_event = decision_event
        self._event_queue.put(("decision_request", request))
        decision_event.wait()
        self._current_decision_event = None
        return self._current_decision_value or "skip_once"

    def _emit_live_process_log(self, entry: ProcessLogEntry) -> None:
        """Forward one live pipeline log entry into the UI event queue."""

        self._event_queue.put(("process_log", entry))

    def _handle_large_root_decision_request(
        self,
        request: ExtractedRootDecisionRequest,
    ) -> None:
        """Show a modal prompt for one large extracted root."""

        lines = [
            f"来源: {request.parent_archive_path}",
            f"文件数: {request.file_count}",
            f"目录树: {request.dir_count}",
        ]
        if request.sample_entries:
            lines.append("内容预览:")
            lines.extend(f"  - {entry}" for entry in request.sample_entries[:12])
        self._current_decision_value = self._show_large_root_decision_dialog(
            title="手动确认大目录",
            message="\n".join(lines),
        )
        if self._current_decision_event is not None:
            self._current_decision_event.set()

    def _show_large_root_decision_dialog(
        self,
        *,
        title: str,
        message: str,
    ) -> DeepProbeDecision:
        """Show a custom modal dialog with three explicit decision buttons."""

        result: dict[str, DeepProbeDecision] = {"value": "skip_once"}
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg="#eef2f6")
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=12)
        container.pack(fill=BOTH, expand=True)

        ttk.Label(
            container,
            text=message,
            justify=LEFT,
            anchor="w",
        ).pack(fill=X)

        button_row = ttk.Frame(container)
        button_row.pack(fill=X, pady=(10, 0))

        def _finish(decision: DeepProbeDecision) -> None:
            result["value"] = decision
            dialog.destroy()

        ttk.Button(
            button_row,
            text="继续",
            style="Primary.TButton",
            command=lambda: _finish("continue"),
        ).pack(side=LEFT)
        ttk.Button(
            button_row,
            text="跳过",
            command=lambda: _finish("skip_once"),
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            button_row,
            text="当前任务默认跳过",
            command=lambda: _finish("skip_default"),
        ).pack(side=RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", lambda: _finish("skip_once"))
        dialog.update_idletasks()
        dialog.geometry(f"+{self.root.winfo_rootx() + 120}+{self.root.winfo_rooty() + 120}")
        dialog.wait_window()
        return result["value"]


def launch_desktop_gui() -> None:
    """Create the Tk root window and start the desktop event loop."""

    root = tk.Tk()
    app = DesktopExtractorApp(root)
    app._log("启动成功：ArcWeaver")
    root.mainloop()


def main() -> None:
    """CLI entry for the desktop application."""

    launch_desktop_gui()


if __name__ == "__main__":
    main()
