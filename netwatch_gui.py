"""
NetWatch — GUI
Dark terminal-inspired interface with a clean data-dense layout.
Requires: Python 3.9+, psutil, requests (tkinter is stdlib)
"""

import tkinter as tk
from tkinter import ttk, font
import threading
import time
import sys
import os
import ctypes
from network_monitor import NetworkMonitor, ConnectionInfo, fmt_rate, fmt_domain, fmt_company


def is_admin() -> bool:
    """Returns True if the process is running with Administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:
        # Non-Windows — fall back to uid check
        try:
            return os.getuid() == 0
        except AttributeError:
            return False


# ─── Theme ────────────────────────────────────────────────────────────────────

COLORS = {
    "bg":           "#0d0f14",
    "bg_panel":     "#13161e",
    "bg_row_even":  "#13161e",
    "bg_row_odd":   "#0f1118",
    "bg_selected":  "#1e2535",
    "accent":       "#00e5ff",       # cyan
    "accent_dim":   "#007a8a",
    "accent_green": "#00ff88",
    "accent_red":   "#ff4455",
    "accent_yellow":"#ffd166",
    "text_primary": "#e8eaf0",
    "text_dim":     "#5a6070",
    "text_header":  "#00e5ff",
    "border":       "#1e2535",
    "border_bright":"#2a3550",
    "scrollbar":    "#1e2535",
}

FONT_MONO  = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 9)
FONT_TITLE = ("Consolas", 18, "bold")
FONT_LABEL = ("Consolas", 9)
FONT_STAT  = ("Consolas", 11, "bold")

COLUMNS = [
    ("process",  "Process",     160),
    ("pid",      "PID",          55),
    ("remote_ip","Remote IP",   130),
    ("domain",   "Domain / Host",200),
    ("company",  "Organization", 180),
    ("country",  "Country Code",            50),
    ("download", "↓ Down",        90),
    ("upload",   "↑ Up",          90),
    ("port",     "Port",          55),
]


# ─── Main Window ──────────────────────────────────────────────────────────────

class NetWatchApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("NetWatch")
        self.geometry("1280x720")
        self.minsize(900, 500)
        self.configure(bg=COLORS["bg"])

        # State
        self._connections: list[ConnectionInfo] = []
        self._lock = threading.Lock()
        self._filter_text = tk.StringVar()
        self._filter_text.trace_add("write", lambda *_: self._apply_filter())
        self._sort_col = "process"
        self._sort_rev = False
        self._selected_ip: str | None = None
        self._total_dl = 0.0
        self._total_ul = 0.0
        self._conn_count = 0

        self._build_ui()
        self._apply_styles()

        # Start monitor
        self.monitor = NetworkMonitor(refresh_interval=2.0)
        self.monitor.on_update = self._on_monitor_update
        self.monitor.start()

        # Animate status dot
        self._dot_state = True
        self._tick_dot()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header bar ──
        header = tk.Frame(self, bg=COLORS["bg"], pady=0)
        header.pack(fill="x", padx=0, pady=0)

        # Left: logo + subtitle
        logo_frame = tk.Frame(header, bg=COLORS["bg"])
        logo_frame.pack(side="left", padx=20, pady=12)

        title_row = tk.Frame(logo_frame, bg=COLORS["bg"])
        title_row.pack(anchor="w")

        self._dot = tk.Label(title_row, text="●", fg=COLORS["accent_green"],
                             bg=COLORS["bg"], font=("Consolas", 14))
        self._dot.pack(side="left", padx=(0, 8))

        tk.Label(title_row, text="NET", fg=COLORS["text_primary"],
                 bg=COLORS["bg"], font=("Consolas", 18, "bold")).pack(side="left")
        tk.Label(title_row, text="WATCH", fg=COLORS["accent"],
                 bg=COLORS["bg"], font=("Consolas", 18, "bold")).pack(side="left")

        tk.Label(logo_frame, text="real-time process network monitor",
                 fg=COLORS["text_dim"], bg=COLORS["bg"],
                 font=("Consolas", 8)).pack(anchor="w", pady=(1, 0))

        # Right: stats strip
        stats_frame = tk.Frame(header, bg=COLORS["bg"])
        stats_frame.pack(side="right", padx=20)

        self._lbl_conns = self._stat_widget(stats_frame, "CONNECTIONS", "0")
        self._lbl_dl    = self._stat_widget(stats_frame, "TOTAL ↓", "0 B/s")
        self._lbl_ul    = self._stat_widget(stats_frame, "TOTAL ↑", "0 B/s")

        # ── Thin accent line ──
        tk.Frame(self, bg=COLORS["accent"], height=1).pack(fill="x")

        # ── Admin warning banner ──
        if not is_admin():
            self._warn_bar = tk.Frame(self, bg="#1e1408")
            self._warn_bar.pack(fill="x")

            tk.Label(
                self._warn_bar,
                text="  ⚠  Not running as Administrator — some system process connections may not be visible.",
                fg=COLORS["accent_yellow"],
                bg="#1e1408",
                font=FONT_LABEL,
                anchor="w",
            ).pack(side="left", pady=5, padx=(0, 12))

            tk.Button(
                self._warn_bar,
                text="Dismiss  ✕",
                command=lambda: self._warn_bar.pack_forget(),
                bg="#1e1408",
                fg=COLORS["text_dim"],
                activebackground="#2a1e0a",
                activeforeground=COLORS["accent_yellow"],
                relief="flat",
                font=FONT_LABEL,
                cursor="hand2",
                bd=0,
            ).pack(side="right", padx=10)

            tk.Frame(self._warn_bar, bg="#3a2800", width=3).pack(side="left", fill="y")

        # ── Toolbar (filter) ──
        toolbar = tk.Frame(self, bg=COLORS["bg_panel"], pady=8)
        toolbar.pack(fill="x")

        tk.Label(toolbar, text="  FILTER", fg=COLORS["text_dim"],
                 bg=COLORS["bg_panel"], font=FONT_LABEL).pack(side="left")

        self._filter_entry = tk.Entry(
            toolbar,
            textvariable=self._filter_text,
            bg=COLORS["bg"],
            fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"],
            relief="flat",
            font=FONT_MONO,
            width=30,
            highlightthickness=1,
            highlightcolor=COLORS["accent"],
            highlightbackground=COLORS["border_bright"],
        )
        self._filter_entry.pack(side="left", padx=(6, 0), ipady=4)

        tk.Label(toolbar, text=" process / IP / company",
                 fg=COLORS["text_dim"], bg=COLORS["bg_panel"],
                 font=FONT_LABEL).pack(side="left")

        # Right: refresh indicator
        self._lbl_refresh = tk.Label(toolbar, text="refreshing every 2s",
                                     fg=COLORS["text_dim"], bg=COLORS["bg_panel"],
                                     font=FONT_LABEL)
        self._lbl_refresh.pack(side="right", padx=16)

        # ── Table area ──
        table_frame = tk.Frame(self, bg=COLORS["bg"])
        table_frame.pack(fill="both", expand=True, padx=0, pady=0)

        # Scrollbars
        vsb = tk.Scrollbar(table_frame, orient="vertical",
                           bg=COLORS["scrollbar"], troughcolor=COLORS["bg"],
                           activebackground=COLORS["accent_dim"], relief="flat",
                           width=10)
        vsb.pack(side="right", fill="y")

        hsb = tk.Scrollbar(table_frame, orient="horizontal",
                           bg=COLORS["scrollbar"], troughcolor=COLORS["bg"],
                           activebackground=COLORS["accent_dim"], relief="flat",
                           width=10)
        hsb.pack(side="bottom", fill="x")

        # Treeview
        col_ids = [c[0] for c in COLUMNS]
        self._tree = ttk.Treeview(
            table_frame,
            columns=col_ids,
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="browse",
        )
        self._tree.pack(fill="both", expand=True)
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        for col_id, col_label, col_width in COLUMNS:
            self._tree.heading(col_id, text=col_label,
                               command=lambda c=col_id: self._sort_by(c))
            self._tree.column(col_id, width=col_width, minwidth=40, anchor="w")

        self._tree.tag_configure("even",      background=COLORS["bg_row_even"], foreground=COLORS["text_primary"])
        self._tree.tag_configure("odd",       background=COLORS["bg_row_odd"],  foreground=COLORS["text_primary"])
        self._tree.tag_configure("selected",  background=COLORS["bg_selected"], foreground=COLORS["accent"])
        self._tree.tag_configure("high_dl",   foreground=COLORS["accent_green"])
        self._tree.tag_configure("high_ul",   foreground=COLORS["accent_yellow"])

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Button-3>", self._on_right_click)

        # ── Status bar ──
        status_bar = tk.Frame(self, bg=COLORS["bg_panel"], height=24)
        status_bar.pack(fill="x", side="bottom")
        tk.Frame(status_bar, bg=COLORS["accent"], height=1).pack(fill="x", side="top")

        self._lbl_status = tk.Label(
            status_bar,
            text="  Starting NetWatch…",
            fg=COLORS["text_dim"],
            bg=COLORS["bg_panel"],
            font=FONT_LABEL,
            anchor="w"
        )
        self._lbl_status.pack(side="left", fill="x", padx=4, pady=3)

        tk.Label(status_bar,
                 text="NetWatch v1.0  •  ip-api.com for IP data  ",
                 fg=COLORS["text_dim"], bg=COLORS["bg_panel"],
                 font=FONT_LABEL).pack(side="right")

    def _stat_widget(self, parent, label: str, value: str):
        """Creates a compact stat box: LABEL / VALUE stacked."""
        frame = tk.Frame(parent, bg=COLORS["bg_panel"],
                         highlightthickness=1,
                         highlightbackground=COLORS["border"])
        frame.pack(side="left", padx=6, pady=8, ipadx=12, ipady=4)

        tk.Label(frame, text=label, fg=COLORS["text_dim"],
                 bg=COLORS["bg_panel"], font=("Consolas", 7)).pack()

        val_lbl = tk.Label(frame, text=value, fg=COLORS["accent"],
                           bg=COLORS["bg_panel"], font=FONT_STAT)
        val_lbl.pack()
        return val_lbl

    # ─── Styles ───────────────────────────────────────────────────────────

    def _apply_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Treeview",
            background=COLORS["bg_row_even"],
            foreground=COLORS["text_primary"],
            fieldbackground=COLORS["bg"],
            borderwidth=0,
            rowheight=26,
            font=FONT_MONO_SM,
        )
        style.configure("Treeview.Heading",
            background=COLORS["bg_panel"],
            foreground=COLORS["text_header"],
            borderwidth=0,
            relief="flat",
            font=("Consolas", 9, "bold"),
            padding=(6, 6),
        )
        style.map("Treeview",
            background=[("selected", COLORS["bg_selected"])],
            foreground=[("selected", COLORS["accent"])],
        )
        style.map("Treeview.Heading",
            background=[("active", COLORS["bg_selected"])],
        )
        style.layout("Treeview", [
            ("Treeview.treearea", {"sticky": "nswe"})
        ])

    # ─── Monitor Callbacks ────────────────────────────────────────────────

    def _on_monitor_update(self, connections: list[ConnectionInfo]):
        """Called from background thread — schedule UI update on main thread."""
        with self._lock:
            self._connections = connections
        self.after(0, self._refresh_table)

    def _refresh_table(self):
        with self._lock:
            conns = list(self._connections)

        # Compute totals
        total_dl = sum(c.download_rate for c in conns)
        total_ul = sum(c.upload_rate for c in conns)

        self._lbl_conns.config(text=str(len(conns)))
        self._lbl_dl.config(text=fmt_rate(total_dl))
        self._lbl_ul.config(text=fmt_rate(total_ul))

        # Apply filter
        flt = self._filter_text.get().lower().strip()
        if flt:
            conns = [c for c in conns if
                     flt in c.process_name.lower() or
                     flt in c.remote_ip.lower() or
                     flt in c.domain.lower() or
                     flt in c.company.lower()]

        # Sort
        conns = self._sort_connections(conns)

        # Repopulate tree
        self._tree.delete(*self._tree.get_children())

        for i, conn in enumerate(conns):
            dl_str = fmt_rate(conn.download_rate)
            ul_str = fmt_rate(conn.upload_rate)

            tags = ["even" if i % 2 == 0 else "odd"]
            if conn.download_rate > 500_000:   # > 500KB/s
                tags.append("high_dl")
            elif conn.upload_rate > 500_000:
                tags.append("high_ul")

            self._tree.insert("", "end", iid=conn.key, tags=tags, values=(
                conn.process_name,
                conn.pid,
                conn.remote_ip,
                fmt_domain(conn),
                fmt_company(conn),
                conn.country or "—",
                dl_str,
                ul_str,
                conn.remote_port,
            ))

        # Update status
        now = time.strftime("%H:%M:%S")
        self._lbl_status.config(
            text=f"  Last updated {now}  •  {len(conns)} connection{'s' if len(conns)!=1 else ''} shown"
        )

    def _apply_filter(self):
        self.after(0, self._refresh_table)

    # ─── Sorting ──────────────────────────────────────────────────────────

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        self._refresh_table()

        # Update heading indicators
        for col_id, col_label, _ in COLUMNS:
            indicator = ""
            if col_id == self._sort_col:
                indicator = " ↑" if not self._sort_rev else " ↓"
            self._tree.heading(col_id, text=col_label + indicator)

    def _sort_connections(self, conns: list[ConnectionInfo]) -> list[ConnectionInfo]:
        key_map = {
            "process":   lambda c: c.process_name.lower(),
            "pid":       lambda c: c.pid,
            "remote_ip": lambda c: c.remote_ip,
            "domain":    lambda c: c.domain.lower(),
            "company":   lambda c: c.company.lower(),
            "country":   lambda c: c.country.lower(),
            "download":  lambda c: c.download_rate,
            "upload":    lambda c: c.upload_rate,
            "port":      lambda c: c.remote_port,
        }
        key_fn = key_map.get(self._sort_col, lambda c: c.process_name.lower())
        return sorted(conns, key=key_fn, reverse=self._sort_rev)

    # ─── Right-click context menu ─────────────────────────────────────────

    def _on_right_click(self, event):
        # Select the row under the cursor first
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)

        vals = self._tree.item(row, "values")
        if not vals:
            return
        proc, pid, ip, domain, company, cc, dl, ul, port = vals

        menu = tk.Menu(self, tearoff=0,
                       bg=COLORS["bg_panel"],
                       fg=COLORS["text_primary"],
                       activebackground=COLORS["bg_selected"],
                       activeforeground=COLORS["accent"],
                       relief="flat",
                       borderwidth=1,
                       font=FONT_MONO_SM)

        # ── Copy options ──
        menu.add_command(
            label=f"  Copy IP Address       {ip}",
            command=lambda: self._copy(ip)
        )
        menu.add_command(
            label=f"  Copy Domain / Host    {domain[:35]}",
            command=lambda: self._copy(domain)
        )
        org_label = company if company and company != "—" else "(unknown)"
        menu.add_command(
            label=f"  Copy Organization     {org_label[:30]}",
            command=lambda: self._copy(company)
        )
        menu.add_command(
            label=f"  Copy Process Name     {proc}",
            command=lambda: self._copy(proc)
        )

        menu.add_separator()

        # ── Filter shortcuts ──
        menu.add_command(
            label=f"  Filter by this process",
            command=lambda: self._set_filter(proc)
        )
        menu.add_command(
            label=f"  Filter by this IP",
            command=lambda: self._set_filter(ip)
        )
        if company and company != "—":
            menu.add_command(
                label=f"  Filter by this organization",
                command=lambda: self._set_filter(company)
            )

        menu.add_separator()
        menu.add_command(label="  Clear filter",
                         command=lambda: self._set_filter(""))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy(self, text: str):
        """Copy text to system clipboard and flash status bar."""
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        prev = self._lbl_status.cget("text")
        self._lbl_status.config(
            text=f"  ✓ Copied to clipboard: {text}",
            fg=COLORS["accent_green"]
        )
        self.after(2000, lambda: self._lbl_status.config(text=prev,
                                                          fg=COLORS["text_dim"]))

    def _set_filter(self, text: str):
        self._filter_text.set(text)
        self._filter_entry.focus_set()

    # ─── Selection ────────────────────────────────────────────────────────

    def _on_select(self, event):
        sel = self._tree.selection()
        if sel:
            iid = sel[0]
            vals = self._tree.item(iid, "values")
            if vals:
                proc, pid, ip, domain, company, cc, dl, ul, port = vals
                self._lbl_status.config(
                    text=f"  {proc} (PID {pid})  →  {domain}  [{ip}:{port}]  •  {company} {cc}  •  ↓{dl}  ↑{ul}"
                )

    # ─── Animated status dot ──────────────────────────────────────────────

    def _tick_dot(self):
        self._dot_state = not self._dot_state
        color = COLORS["accent_green"] if self._dot_state else COLORS["accent_dim"]
        self._dot.config(fg=color)
        self.after(900, self._tick_dot)

    # ─── Cleanup ──────────────────────────────────────────────────────────

    def _on_close(self):
        self.monitor.stop()
        self.destroy()


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    app = NetWatchApp()
    app.mainloop()


if __name__ == "__main__":
    main()