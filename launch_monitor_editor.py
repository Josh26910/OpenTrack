#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenTrack Studio — TrackMan-inspired Launch Monitor Video Editor
================================================================

A single-file desktop application for turning ordinary golf swing videos into
premium, TrackMan-style traced shots.

Workflow
--------
1.  LOAD      Upload an .mp4 / .mov video from the left sidebar.
2.  CALIBRATE Toggle "Draw Calibration Line", drag a line over a known
              distance in the frame (driver length, 100-yd sign, ...) and
              enter its real-world length. This converts pixels -> yards.
3.  MARK      Step frame-by-frame from impact and click the centre of the
              ball for at least 3 frames (each click auto-advances 1 frame).
              Then scrub to the peak and click "Mark Apex", and scrub to the
              landing and click "Mark Landing".
4.  TRACK     Press TRACK SHOT. A physics-assisted projectile fit connects
              the launch clicks through the apex down to the landing point.
              Ball speed is computed directly from the pixel distance between
              your manual clicks relative to the video FPS.
5.  PLAY      A hollow TrackMan-orange ring follows the ball on every frame
              (cleanly clipping at the frame edges when the path leaves the
              picture, and fluidly reappearing when it returns). When playback
              reaches the apex frame, semi-transparent stat tiles fade in:
              Ball Speed, Carry, Launch Angle and Height. Double-click any
              tile to type in your own numbers from a pocket launch monitor.

Dependencies
------------
    pip install customtkinter opencv-python numpy scipy Pillow
"""

import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import numpy as np
import customtkinter as ctk
from PIL import Image, ImageTk
from scipy.optimize import curve_fit

# --------------------------------------------------------------------------- #
#  Palette / constants
# --------------------------------------------------------------------------- #

TM_ORANGE      = "#FF5A00"          # TrackMan orange
TM_ORANGE_DARK = "#C24500"
BG_ROOT        = "#0E0E10"          # near-black charcoal
BG_PANEL       = "#161618"
BG_PANEL_2     = "#1D1D21"
BG_WIDGET      = "#26262B"
FG_TEXT        = "#F2F2F2"
FG_MUTED       = "#98989E"
BORDER         = "#2C2C31"

# OpenCV works in BGR
ORANGE_BGR = (0, 90, 255)           # FF5A00
WHITE_BGR  = (245, 245, 245)
GREY_BGR   = (150, 150, 155)
DARK_BGR   = (22, 22, 25)
BLACK_BGR  = (5, 5, 5)

UNIT_TO_YARDS = {
    "yards":  1.0,
    "feet":   1.0 / 3.0,
    "meters": 1.09361,
    "inches": 1.0 / 36.0,
}

YPS_TO_MPH   = 3600.0 / 1760.0      # yards/second -> miles/hour
YARDS_TO_FT  = 3.0

# (key, tile label, unit, decimals)
STAT_DEFS = [
    ("ball_speed", "BALL SPEED",   "mph", 1),
    ("carry",      "CARRY",        "yds", 1),
    ("launch",     "LAUNCH ANGLE", "deg", 1),
    ("height",     "HEIGHT (APEX)", "ft", 0),
]

MODE_IDLE      = "idle"
MODE_LAUNCH    = "launch"
MODE_APEX      = "apex"
MODE_LANDING   = "landing"
MODE_CALIBRATE = "calibrate"


def _fit_font_scale(text, target_h, font=cv2.FONT_HERSHEY_DUPLEX):
    """Return a cv2 font scale so `text` renders roughly `target_h` px tall."""
    (_, base_h), _ = cv2.getTextSize(text, font, 1.0, 2)
    if base_h <= 0:
        return 0.5
    return max(0.3, target_h / float(base_h))


def _put_text_centered(img, text, cx, cy_baseline, scale, color, thickness,
                       font=cv2.FONT_HERSHEY_DUPLEX):
    """Draw text horizontally centred on cx with baseline at cy_baseline."""
    (tw, _), _ = cv2.getTextSize(text, font, scale, thickness)
    org = (int(cx - tw / 2), int(cy_baseline))
    cv2.putText(img, text, org, font, scale, color, thickness, cv2.LINE_AA)
    return org, tw


def _rotate_frame(frame, degrees):
    """Rotate frame by 0, 90, 180, or 270 degrees clockwise."""
    if degrees == 0:
        return frame
    if degrees == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


# --------------------------------------------------------------------------- #
#  Main application
# --------------------------------------------------------------------------- #

class LaunchMonitorApp(ctk.CTk):
    """TrackMan-style manual launch monitor video editor."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        self.title("OpenTrack Studio  —  Launch Monitor Editor")
        self.geometry("1440x860")
        self.minsize(1100, 680)
        self.configure(fg_color=BG_ROOT)

        # ---------------- video state ----------------
        self.cap = None
        self.video_path = None
        self.fps = 30.0
        self.frame_count = 0
        self.frame_w = 0
        self.frame_h = 0
        self.current_idx = 0
        self.rotation = 0              # 0, 90, 180, 270 degrees

        self._cached_idx = -1
        self._cached_frame = None      # raw BGR frame at _cached_idx
        self._cap_next = 0             # index the capture will read next

        self.playing = False
        self._play_job = None

        # ---------------- shot marking ----------------
        self.mode = MODE_IDLE
        self.launch_clicks = []        # [(frame_idx, x, y), ...]  video coords
        self.apex_click = None         # (frame_idx, x, y)
        self.landing_click = None      # (frame_idx, x, y)

        # ---------------- calibration ----------------
        self.yards_per_px = None
        self._cal_start = None         # (x, y) video coords while dragging
        self._cal_current = None
        self._cal_line = None          # finished ((x1,y1),(x2,y2)) for display

        # ---------------- trajectory / stats ----------------
        self.trajectory = None         # {frame_idx: (x, y)} fitted path
        self.impact_frame = None
        self.apex_frame = None
        self.landing_frame = None
        self.stats = {}                # computed values (may hold None)
        self.overrides = {}            # user-typed values from tile edits
        self._tile_rects = {}          # {key: (x1,y1,x2,y2)} video coords

        # ---------------- display transform ----------------
        # (scale, offset_x, offset_y, disp_w, disp_h) canvas <-> video mapping
        self._disp = None
        self._photo = None

        # ---------------- UI ----------------
        self._slider_guard = False
        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_status("Load a video to begin.")
        self._render()

    # ================================================================== #
    #  UI construction
    # ================================================================== #

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._build_sidebar()
        self._build_center()
        self._build_bottom_bar()

    # ------------------------------ sidebar --------------------------- #

    def _build_sidebar(self):
        sb = ctk.CTkScrollableFrame(
            self, width=290, corner_radius=0,
            fg_color=BG_PANEL, scrollbar_button_color=BG_WIDGET,
            scrollbar_button_hover_color=TM_ORANGE_DARK,
        )
        sb.grid(row=0, column=0, sticky="nsw")
        self.sidebar = sb

        # -- brand header ------------------------------------------------
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 4))
        ctk.CTkLabel(
            brand, text="OPENTRACK",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=FG_TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            brand, text=" STUDIO",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TM_ORANGE,
        ).pack(side="left")
        ctk.CTkLabel(
            sb, text="MANUAL LAUNCH MONITOR EDITOR",
            font=ctk.CTkFont(size=10),
            text_color=FG_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # -- 1. video ------------------------------------------------------
        self._section(sb, "1  ·  VIDEO")
        ctk.CTkButton(
            sb, text="⬆  UPLOAD VIDEO", height=38,
            fg_color=TM_ORANGE, hover_color=TM_ORANGE_DARK,
            text_color="#000000", font=ctk.CTkFont(size=13, weight="bold"),
            command=self.open_video,
        ).pack(fill="x", padx=16, pady=(4, 4))
        self.video_info_lbl = ctk.CTkLabel(
            sb, text="No video loaded", font=ctk.CTkFont(size=11),
            text_color=FG_MUTED, justify="left", anchor="w", wraplength=250,
        )
        self.video_info_lbl.pack(fill="x", padx=16, pady=(0, 6))

        # -- rotation -------------------------------------------------------
        rot_row = ctk.CTkFrame(sb, fg_color="transparent")
        rot_row.pack(fill="x", padx=16, pady=(4, 4))
        ctk.CTkButton(
            rot_row, text="↺", width=44, height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1,
            text_color=FG_TEXT, font=ctk.CTkFont(size=16, weight="bold"),
            command=self._rotate_ccw,
        ).pack(side="left", padx=2)
        self.rotation_lbl = ctk.CTkLabel(
            rot_row, text="0°", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TM_ORANGE, width=60,
        )
        self.rotation_lbl.pack(side="left", padx=4)
        ctk.CTkButton(
            rot_row, text="↻", width=44, height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1,
            text_color=FG_TEXT, font=ctk.CTkFont(size=16, weight="bold"),
            command=self._rotate_cw,
        ).pack(side="left", padx=2)

        # -- 2. calibration -------------------------------------------------
        self._section(sb, "2  ·  CALIBRATION")
        self.cal_btn = ctk.CTkButton(
            sb, text="📏  DRAW CALIBRATION LINE", height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1,
            text_color=FG_TEXT, font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_mode(MODE_CALIBRATE),
        )
        self.cal_btn.pack(fill="x", padx=16, pady=(4, 6))

        row = ctk.CTkFrame(sb, fg_color="transparent")
        row.pack(fill="x", padx=16)
        self.cal_dist_entry = ctk.CTkEntry(
            row, placeholder_text="Known distance",
            fg_color=BG_WIDGET, border_color=BORDER, text_color=FG_TEXT,
        )
        self.cal_dist_entry.pack(side="left", fill="x", expand=True)
        self.cal_unit_menu = ctk.CTkOptionMenu(
            row, values=list(UNIT_TO_YARDS.keys()), width=92,
            fg_color=BG_WIDGET, button_color=BG_WIDGET,
            button_hover_color=TM_ORANGE_DARK, text_color=FG_TEXT,
            dropdown_fg_color=BG_PANEL_2,
        )
        self.cal_unit_menu.set("yards")
        self.cal_unit_menu.pack(side="left", padx=(8, 0))

        self.cal_status_lbl = ctk.CTkLabel(
            sb, text="Not calibrated — stats will show '--'",
            font=ctk.CTkFont(size=11), text_color=FG_MUTED,
            anchor="w", wraplength=250, justify="left",
        )
        self.cal_status_lbl.pack(fill="x", padx=16, pady=(4, 6))

        # -- 3. mark the shot ----------------------------------------------
        self._section(sb, "3  ·  MARK THE SHOT")
        self.mode_buttons = {}

        self.mode_buttons[MODE_LAUNCH] = ctk.CTkButton(
            sb, text="⨁  CLICK BALL — LAUNCH FRAMES", height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_mode(MODE_LAUNCH),
        )
        self.mode_buttons[MODE_LAUNCH].pack(fill="x", padx=16, pady=(4, 3))

        self.launch_count_lbl = ctk.CTkLabel(
            sb, text="Launch clicks: 0   (minimum 3)",
            font=ctk.CTkFont(size=11), text_color=FG_MUTED, anchor="w",
        )
        self.launch_count_lbl.pack(fill="x", padx=16)

        self.mode_buttons[MODE_APEX] = ctk.CTkButton(
            sb, text="⌂  MARK APEX", height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_mode(MODE_APEX),
        )
        self.mode_buttons[MODE_APEX].pack(fill="x", padx=16, pady=(6, 3))
        self.apex_lbl = ctk.CTkLabel(
            sb, text="Apex: not set", font=ctk.CTkFont(size=11),
            text_color=FG_MUTED, anchor="w",
        )
        self.apex_lbl.pack(fill="x", padx=16)

        self.mode_buttons[MODE_LANDING] = ctk.CTkButton(
            sb, text="⌄  MARK LANDING POINT", height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_mode(MODE_LANDING),
        )
        self.mode_buttons[MODE_LANDING].pack(fill="x", padx=16, pady=(6, 3))
        self.landing_lbl = ctk.CTkLabel(
            sb, text="Landing: not set", font=ctk.CTkFont(size=11),
            text_color=FG_MUTED, anchor="w",
        )
        self.landing_lbl.pack(fill="x", padx=16, pady=(0, 4))

        # -- 4. track / clear ------------------------------------------------
        self._section(sb, "4  ·  TRACK")
        ctk.CTkButton(
            sb, text="●  TRACK SHOT", height=42,
            fg_color=TM_ORANGE, hover_color=TM_ORANGE_DARK,
            text_color="#000000", font=ctk.CTkFont(size=14, weight="bold"),
            command=self.track_shot,
        ).pack(fill="x", padx=16, pady=(4, 4))
        ctk.CTkButton(
            sb, text="✕  CLEAR MARKS & TRACK", height=30,
            fg_color=BG_WIDGET, hover_color="#3A2020",
            border_color=BORDER, border_width=1, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12),
            command=self.clear_marks,
        ).pack(fill="x", padx=16, pady=(0, 6))

        # -- 5. data layout ---------------------------------------------------
        self._section(sb, "5  ·  DATA LAYOUT")
        self.show_ring_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            sb, text="Tracking ring", variable=self.show_ring_var,
            command=self._render, checkbox_height=18, checkbox_width=18,
            fg_color=TM_ORANGE, hover_color=TM_ORANGE_DARK,
            border_color=BORDER, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=16, pady=(4, 2))

        self.tile_vars = {}
        for key, label, _unit, _dec in STAT_DEFS:
            var = ctk.BooleanVar(value=True)
            self.tile_vars[key] = var
            ctk.CTkCheckBox(
                sb, text=f"Tile — {label.title()}", variable=var,
                command=self._render, checkbox_height=18, checkbox_width=18,
                fg_color=TM_ORANGE, hover_color=TM_ORANGE_DARK,
                border_color=BORDER, text_color=FG_TEXT,
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=16, pady=2)

        # -- shot data readout -------------------------------------------------
        self._section(sb, "SHOT DATA")
        ctk.CTkLabel(
            sb, text="Double-click a tile on the video to override a value.",
            font=ctk.CTkFont(size=10), text_color=FG_MUTED,
            wraplength=250, justify="left", anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 4))

        self.stat_value_lbls = {}
        for key, label, unit, _dec in STAT_DEFS:
            row = ctk.CTkFrame(sb, fg_color=BG_PANEL_2, corner_radius=6)
            row.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(
                row, text=label, font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TM_ORANGE,
            ).pack(side="left", padx=(10, 4), pady=6)
            lbl = ctk.CTkLabel(
                row, text=f"--  {unit}",
                font=ctk.CTkFont(size=13, weight="bold"), text_color=FG_TEXT,
            )
            lbl.pack(side="right", padx=(4, 10), pady=6)
            self.stat_value_lbls[key] = lbl

        ctk.CTkLabel(sb, text=" ", font=ctk.CTkFont(size=6)).pack(pady=4)

    def _section(self, parent, title):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            bar, text=title, font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TM_ORANGE, anchor="w",
        ).pack(side="left")
        line = ctk.CTkFrame(bar, height=1, fg_color=BORDER)
        line.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=1)

    # ------------------------------ centre ---------------------------- #

    def _build_center(self):
        center = ctk.CTkFrame(self, fg_color=BG_ROOT, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew")
        center.grid_rowconfigure(0, weight=1)
        center.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            center, bg=BG_ROOT, highlightthickness=0, bd=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.canvas.bind("<Configure>", lambda e: self._render())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)

    # ---------------------------- bottom bar -------------------------- #

    def _build_bottom_bar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=96)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)

        # transport buttons
        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.grid(row=0, column=0, padx=(14, 8), pady=(10, 2), sticky="w")

        def transport(text, cmd, w=44, accent=False):
            return ctk.CTkButton(
                btns, text=text, width=w, height=34, command=cmd,
                fg_color=TM_ORANGE if accent else BG_WIDGET,
                hover_color=TM_ORANGE_DARK if accent else BG_PANEL_2,
                text_color="#000000" if accent else FG_TEXT,
                border_color=BORDER, border_width=0 if accent else 1,
                font=ctk.CTkFont(size=14, weight="bold"),
            )

        self.back_btn = transport("⏮", lambda: self.step(-1))
        self.back_btn.pack(side="left", padx=2)
        self.play_btn = transport("▶", self.toggle_play, w=56, accent=True)
        self.play_btn.pack(side="left", padx=2)
        self.fwd_btn = transport("⏭", lambda: self.step(1))
        self.fwd_btn.pack(side="left", padx=2)

        # frame / time label
        self.frame_lbl = ctk.CTkLabel(
            bar, text="frame  —  /  —", width=190,
            font=ctk.CTkFont(size=12, weight="bold"), text_color=FG_MUTED,
        )
        self.frame_lbl.grid(row=0, column=1, padx=6, pady=(10, 2))

        # timeline slider
        self.slider = ctk.CTkSlider(
            bar, from_=0, to=1, number_of_steps=1,
            command=self._on_slider,
            progress_color=TM_ORANGE, button_color=TM_ORANGE,
            button_hover_color="#FF7A30", fg_color=BG_WIDGET, height=18,
        )
        self.slider.set(0)
        self.slider.grid(row=0, column=2, sticky="ew", padx=(6, 18),
                         pady=(10, 2))

        # status line
        self.status_lbl = ctk.CTkLabel(
            bar, text="", font=ctk.CTkFont(size=11), text_color=FG_MUTED,
            anchor="w",
        )
        self.status_lbl.grid(row=1, column=0, columnspan=3, sticky="ew",
                             padx=16, pady=(0, 8))

    def _bind_keys(self):
        self.bind("<space>", lambda e: self._hotkey(self.toggle_play))
        self.bind("<Left>", lambda e: self._hotkey(lambda: self.step(-1)))
        self.bind("<Right>", lambda e: self._hotkey(lambda: self.step(1)))

    def _hotkey(self, action):
        """Run a transport hotkey unless the user is typing in an entry."""
        focus = self.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text)):
            return
        action()

    def _rotate_cw(self):
        """Rotate video 90 degrees clockwise."""
        if self.cap is None:
            return
        self.rotation = (self.rotation + 90) % 360
        self.rotation_lbl.configure(text=f"{self.rotation}°")
        self._render()

    def _rotate_ccw(self):
        """Rotate video 90 degrees counter-clockwise."""
        if self.cap is None:
            return
        self.rotation = (self.rotation - 90) % 360
        self.rotation_lbl.configure(text=f"{self.rotation}°")
        self._render()

    # ================================================================== #
    #  Video handling
    # ================================================================== #

    def open_video(self):
        path = filedialog.askopenfilename(
            title="Select a golf shot video",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.MP4 *.MOV"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            messagebox.showerror(
                "Video Error",
                "Could not open the selected file.\n"
                "Make sure it is a valid .mp4 or .mov video.",
            )
            return

        ok, first = cap.read()
        if not ok or first is None:
            cap.release()
            messagebox.showerror(
                "Video Error", "The video appears to be empty or corrupt.",
            )
            return

        # swap in the new capture
        self._stop_play()
        if self.cap is not None:
            self.cap.release()

        self.cap = cap
        self.video_path = path
        fps = cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and fps > 1 else 30.0
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_count = count if count > 0 else 1
        self.frame_h, self.frame_w = first.shape[:2]

        self._cached_idx = 0
        self._cached_frame = first
        self._cap_next = 1
        self.current_idx = 0
        self.rotation = 0
        self.rotation_lbl.configure(text="0°")

        # reset shot data (keep calibration only if same session scale wanted;
        # a new video means a new camera position, so reset it too)
        self.yards_per_px = None
        self._cal_line = None
        self.cal_status_lbl.configure(
            text="Not calibrated — stats will show '--'")
        self.clear_marks(silent=True)

        # timeline
        steps = max(1, self.frame_count - 1)
        self.slider.configure(from_=0, to=steps, number_of_steps=steps)
        self._slider_guard = True
        self.slider.set(0)
        self._slider_guard = False

        name = os.path.basename(path)
        self.video_info_lbl.configure(
            text=f"{name}\n{self.frame_w}×{self.frame_h}  ·  "
                 f"{self.fps:.2f} fps  ·  {self.frame_count} frames",
        )
        self._set_status(
            "Video loaded. Calibrate, then step to impact and click the ball.")
        self._render()

    def _get_frame(self, idx):
        """Return the raw BGR frame at idx (cached / sequential-read aware)."""
        if self.cap is None:
            return None
        idx = max(0, min(idx, self.frame_count - 1))

        if idx == self._cached_idx and self._cached_frame is not None:
            return self._cached_frame

        try:
            if idx != self._cap_next:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = self.cap.read()
        except cv2.error:
            ok, frame = False, None

        if not ok or frame is None:
            # keep showing the last good frame rather than glitching
            return self._cached_frame

        self._cap_next = idx + 1
        self._cached_idx = idx
        self._cached_frame = frame
        return frame

    def seek(self, idx, from_slider=False):
        if self.cap is None:
            return
        idx = int(max(0, min(idx, self.frame_count - 1)))
        self.current_idx = idx
        if not from_slider:
            self._slider_guard = True
            self.slider.set(idx)
            self._slider_guard = False
        self._update_frame_label()
        self._render()

    def step(self, delta):
        if self.cap is None:
            return
        self._stop_play()
        self.seek(self.current_idx + delta)

    def _on_slider(self, value):
        if self._slider_guard:
            return
        self._stop_play()
        self.seek(int(round(float(value))), from_slider=True)

    def toggle_play(self):
        if self.cap is None:
            return
        if self.playing:
            self._stop_play()
        else:
            if self.current_idx >= self.frame_count - 1:
                self.seek(0)
            self.playing = True
            self.play_btn.configure(text="❚❚")
            self._play_tick()

    def _play_tick(self):
        if not self.playing or self.cap is None:
            return
        if self.current_idx >= self.frame_count - 1:
            self._stop_play()
            return
        self.seek(self.current_idx + 1)
        delay = max(1, int(round(1000.0 / self.fps)))
        self._play_job = self.after(delay, self._play_tick)

    def _stop_play(self):
        self.playing = False
        if self._play_job is not None:
            try:
                self.after_cancel(self._play_job)
            except Exception:
                pass
            self._play_job = None
        self.play_btn.configure(text="▶")

    def _update_frame_label(self):
        secs = self.current_idx / self.fps if self.fps else 0.0
        self.frame_lbl.configure(
            text=f"frame  {self.current_idx}  /  {self.frame_count - 1}"
                 f"    {secs:6.2f}s",
        )

    # ================================================================== #
    #  Coordinate mapping (canvas <-> video)
    # ================================================================== #

    def _canvas_to_video(self, cx, cy):
        """Map a canvas click to video-pixel coordinates (or None)."""
        if self._disp is None or self.cap is None:
            return None
        scale, ox, oy, dw, dh = self._disp
        if not (ox <= cx <= ox + dw and oy <= cy <= oy + dh):
            return None

        # from canvas to rotated frame space
        rx = (cx - ox) / scale
        ry = (cy - oy) / scale

        # dimensions of rotated frame
        if self.rotation in (90, 270):
            rot_w, rot_h = self.frame_h, self.frame_w
        else:
            rot_w, rot_h = self.frame_w, self.frame_h

        rx = min(max(rx, 0), rot_w - 1)
        ry = min(max(ry, 0), rot_h - 1)

        # from rotated frame space back to original frame space
        if self.rotation == 0:
            vx, vy = rx, ry
        elif self.rotation == 90:
            vx, vy = ry, self.frame_w - rx
        elif self.rotation == 180:
            vx, vy = self.frame_w - rx, self.frame_h - ry
        elif self.rotation == 270:
            vx, vy = self.frame_h - ry, rx
        else:
            vx, vy = rx, ry

        vx = min(max(vx, 0), self.frame_w - 1)
        vy = min(max(vy, 0), self.frame_h - 1)
        return (float(vx), float(vy))

    # ================================================================== #
    #  Mouse interaction
    # ================================================================== #

    def _set_mode(self, mode):
        if self.cap is None:
            self._set_status("Load a video first.")
            return
        # clicking the active mode button toggles back to idle
        self.mode = MODE_IDLE if self.mode == mode else mode
        self._cal_start = None
        self._cal_current = None

        # style the buttons
        for m, btn in self.mode_buttons.items():
            active = (m == self.mode)
            btn.configure(
                fg_color=TM_ORANGE if active else BG_WIDGET,
                text_color="#000000" if active else FG_TEXT,
            )
        cal_active = (self.mode == MODE_CALIBRATE)
        self.cal_btn.configure(
            fg_color=TM_ORANGE if cal_active else BG_WIDGET,
            text_color="#000000" if cal_active else FG_TEXT,
        )

        cursor = "crosshair" if self.mode != MODE_IDLE else ""
        self.canvas.configure(cursor=cursor)

        hints = {
            MODE_IDLE: "Ready.",
            MODE_LAUNCH: "Step to impact and click the centre of the ball. "
                         "Each click auto-advances one frame (min 3 clicks).",
            MODE_APEX: "Scrub to the peak of the flight and click the ball.",
            MODE_LANDING: "Scrub to the landing and click where the ball "
                          "touches down.",
            MODE_CALIBRATE: "Drag a line over a known distance in the frame, "
                            "then enter its length in the sidebar box.",
        }
        self._set_status(hints[self.mode])
        self._render()

    def _on_press(self, event):
        if self.cap is None:
            return
        pt = self._canvas_to_video(event.x, event.y)
        if pt is None:
            return

        if self.mode == MODE_CALIBRATE:
            self._cal_start = pt
            self._cal_current = pt
            self._render()
            return

        if self.mode == MODE_LAUNCH:
            self._stop_play()
            self.launch_clicks.append((self.current_idx, pt[0], pt[1]))
            self.launch_clicks.sort(key=lambda p: p[0])
            n = len(self.launch_clicks)
            self.launch_count_lbl.configure(
                text=f"Launch clicks: {n}   (minimum 3)")
            self._set_status(
                f"Launch click {n} recorded on frame {self.current_idx}. "
                "Auto-advanced to the next frame.")
            # auto-advance to make frame-by-frame clicking effortless
            if self.current_idx < self.frame_count - 1:
                self.seek(self.current_idx + 1)
            else:
                self._render()
            return

        if self.mode == MODE_APEX:
            self._stop_play()
            self.apex_click = (self.current_idx, pt[0], pt[1])
            self.apex_lbl.configure(
                text=f"Apex: frame {self.current_idx}")
            self._set_status(f"Apex marked on frame {self.current_idx}.")
            self._render()
            return

        if self.mode == MODE_LANDING:
            self._stop_play()
            self.landing_click = (self.current_idx, pt[0], pt[1])
            self.landing_lbl.configure(
                text=f"Landing: frame {self.current_idx}")
            self._set_status(f"Landing marked on frame {self.current_idx}.")
            self._render()
            return

    def _on_drag(self, event):
        if self.mode == MODE_CALIBRATE and self._cal_start is not None:
            pt = self._canvas_to_video(event.x, event.y)
            if pt is not None:
                self._cal_current = pt
                self._render()

    def _on_release(self, event):
        if self.mode != MODE_CALIBRATE or self._cal_start is None:
            return
        pt = self._canvas_to_video(event.x, event.y)
        if pt is not None:
            self._cal_current = pt
        self._finish_calibration()

    def _on_double_click(self, event):
        """Double-click on a visible stat tile -> manual value override."""
        if not self._tile_rects or self.trajectory is None:
            return
        if self.apex_frame is None or self.current_idx < self.apex_frame:
            return
        pt = self._canvas_to_video(event.x, event.y)
        if pt is None:
            return
        for key, (x1, y1, x2, y2) in self._tile_rects.items():
            if x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2:
                self._edit_stat(key)
                return

    # ================================================================== #
    #  Calibration
    # ================================================================== #

    def _finish_calibration(self):
        p1, p2 = self._cal_start, self._cal_current
        self._cal_start = None
        self._cal_current = None

        if p1 is None or p2 is None:
            return
        length_px = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if length_px < 5:
            self._set_status(
                "Calibration line too short — drag a longer line.")
            self._render()
            return

        # read the distance from the sidebar; ask via dialog if empty/invalid
        raw = self.cal_dist_entry.get().strip()
        value = None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            dlg = ctk.CTkInputDialog(
                title="Calibration distance",
                text=f"Enter the real-world length of the line you drew "
                     f"({self.cal_unit_menu.get()}):",
            )
            raw = dlg.get_input()
            try:
                value = float(raw) if raw else None
            except (TypeError, ValueError):
                value = None

        if value is None or value <= 0:
            self._set_status("Calibration cancelled — no valid distance.")
            self._render()
            return

        yards = value * UNIT_TO_YARDS[self.cal_unit_menu.get()]
        self.yards_per_px = yards / length_px
        self._cal_line = (p1, p2)
        self.cal_status_lbl.configure(
            text=f"Calibrated:  1 px = {self.yards_per_px:.4f} yd   "
                 f"({length_px:.0f} px = {value:g} {self.cal_unit_menu.get()})",
        )
        # if a shot is already tracked, refresh its real-world stats
        if self.trajectory is not None:
            self._compute_stats()
            self._update_sidebar_stats()
        self._set_mode(MODE_CALIBRATE)   # toggles back to idle
        self._set_status("Calibration saved.")
        self._render()

    # ================================================================== #
    #  Trajectory fitting & stats
    # ================================================================== #

    def track_shot(self):
        if self.cap is None:
            messagebox.showwarning("No video", "Load a video first.")
            return
        if len(self.launch_clicks) < 3:
            messagebox.showwarning(
                "Need more launch clicks",
                "Click the centre of the ball on at least 3 consecutive "
                "frames starting at impact.",
            )
            return
        if self.apex_click is None or self.landing_click is None:
            messagebox.showwarning(
                "Missing marks",
                "Mark both the Apex and the Landing Point before tracking.",
            )
            return

        f0 = self.launch_clicks[0][0]
        f_last_launch = self.launch_clicks[-1][0]
        f_apex = self.apex_click[0]
        f_land = self.landing_click[0]
        if not (f0 < f_apex < f_land) or f_apex <= f_last_launch:
            messagebox.showwarning(
                "Frame order problem",
                "Frames must be ordered: launch clicks  →  apex  →  landing.\n"
                f"Got launch {f0}-{f_last_launch}, apex {f_apex}, "
                f"landing {f_land}.",
            )
            return

        try:
            self._fit_trajectory()
        except Exception as exc:                       # noqa: BLE001
            messagebox.showerror(
                "Tracking failed",
                f"Could not fit a trajectory to the clicks:\n{exc}",
            )
            return

        self._compute_stats()
        self._update_sidebar_stats()

        if self.yards_per_px is None:
            self._set_status(
                "Shot tracked — calibrate to unlock real-world numbers, "
                "or double-click the tiles to type your own.")
        else:
            self._set_status("Shot tracked. Press play to watch the trace.")

        # cue the video back to impact so the user can hit play immediately
        self.seek(self.impact_frame)

    def _fit_trajectory(self):
        """
        Physics-assisted projectile fit.

        Both x(t) and y(t) are modelled as quadratics in time — exactly the
        form of projectile motion (constant acceleration). The fit is a
        weighted least-squares through every manual click, with the apex and
        landing points weighted heavily so the curve passes smoothly through
        the user's launch clicks, over the apex, and down to the landing.
        """
        f0 = self.launch_clicks[0][0]
        fps = self.fps

        pts = list(self.launch_clicks) + [self.apex_click, self.landing_click]
        ts = np.array([(f - f0) / fps for (f, _x, _y) in pts], dtype=float)
        xs = np.array([x for (_f, x, _y) in pts], dtype=float)
        ys = np.array([y for (_f, _x, y) in pts], dtype=float)

        n_launch = len(self.launch_clicks)
        weights = np.ones(len(pts), dtype=float)
        weights[0] = 5.0          # impact point — anchor the start
        weights[n_launch] = 8.0   # apex
        weights[n_launch + 1] = 8.0  # landing
        sigma = 1.0 / weights

        def quad(t, a, b, c):
            return a * t * t + b * t + c

        # seed with an unweighted polyfit, refine with weighted least squares
        px0 = np.polyfit(ts, xs, 2)
        py0 = np.polyfit(ts, ys, 2)
        (ax, bx, cx), _ = curve_fit(quad, ts, xs, p0=px0, sigma=sigma,
                                    absolute_sigma=False, maxfev=10000)
        (ay, by, cy), _ = curve_fit(quad, ts, ys, p0=py0, sigma=sigma,
                                    absolute_sigma=False, maxfev=10000)

        self._fit_x = (ax, bx, cx)
        self._fit_y = (ay, by, cy)

        self.impact_frame = f0
        self.apex_frame = self.apex_click[0]
        self.landing_frame = self.landing_click[0]

        traj = {}
        for f in range(f0, self.landing_frame + 1):
            t = (f - f0) / fps
            x = ax * t * t + bx * t + cx
            y = ay * t * t + by * t + cy
            traj[f] = (x, y)
        self.trajectory = traj

    def _compute_stats(self):
        """Fill self.stats from clicks + fit (None where uncalibrated)."""
        scale = self.yards_per_px
        stats = {"ball_speed": None, "carry": None,
                 "launch": None, "height": None}

        # --- ball speed: straight from the pixel distance between clicks ---
        px_speeds = []
        for (fa, xa, ya), (fb, xb, yb) in zip(self.launch_clicks,
                                              self.launch_clicks[1:]):
            df = fb - fa
            if df <= 0:
                continue
            dist_px = math.hypot(xb - xa, yb - ya)
            px_speeds.append(dist_px * self.fps / df)   # px / second
        px_per_s = float(np.mean(px_speeds)) if px_speeds else 0.0
        if scale is not None and px_per_s > 0:
            stats["ball_speed"] = px_per_s * scale * YPS_TO_MPH

        # --- launch angle: initial velocity direction of the fitted path ---
        try:
            _ax, bx, _cx = self._fit_x
            _ay, by, _cy = self._fit_y
            vx0 = bx                       # px/s horizontal at t = 0
            vy0 = -by                      # screen y is inverted
            if abs(vx0) > 1e-6 or abs(vy0) > 1e-6:
                stats["launch"] = math.degrees(
                    math.atan2(vy0, abs(vx0)))
        except AttributeError:
            pass

        # --- carry: impact -> landing distance in the frame plane ---
        f0, x0, y0 = self.launch_clicks[0]
        _fl, xl, yl = self.landing_click
        if scale is not None:
            stats["carry"] = math.hypot(xl - x0, yl - y0) * scale

        # --- height: fitted apex height above the impact point ---
        if scale is not None:
            ay, by, cy = self._fit_y
            if abs(ay) > 1e-9:
                t_apex = -by / (2.0 * ay)
                y_apex = ay * t_apex * t_apex + by * t_apex + cy
            else:
                y_apex = self.apex_click[2]
            h_px = max(0.0, y0 - y_apex)
            stats["height"] = h_px * scale * YARDS_TO_FT

        self.stats = stats

    def clear_marks(self, silent=False):
        self.launch_clicks = []
        self.apex_click = None
        self.landing_click = None
        self.trajectory = None
        self.impact_frame = None
        self.apex_frame = None
        self.landing_frame = None
        self.stats = {}
        self.overrides = {}
        self._tile_rects = {}
        if hasattr(self, "_fit_x"):
            del self._fit_x
        if hasattr(self, "_fit_y"):
            del self._fit_y

        self.launch_count_lbl.configure(text="Launch clicks: 0   (minimum 3)")
        self.apex_lbl.configure(text="Apex: not set")
        self.landing_lbl.configure(text="Landing: not set")
        self._update_sidebar_stats()
        if not silent:
            self._set_status("Marks and track cleared.")
            self._render()

    # ================================================================== #
    #  Stat tiles: display + editing
    # ================================================================== #

    def _stat_display_value(self, key):
        """Override wins over computed value; None -> '--'."""
        if key in self.overrides:
            return self.overrides[key]
        return self.stats.get(key)

    def _edit_stat(self, key):
        meta = {k: (label, unit, dec) for k, label, unit, dec in STAT_DEFS}
        label, unit, _dec = meta[key]
        current = self._stat_display_value(key)
        hint = f" (currently {current:.1f})" if current is not None else ""
        dlg = ctk.CTkInputDialog(
            title=f"Override {label.title()}",
            text=f"Enter {label.title()} in {unit}{hint}:",
        )
        raw = dlg.get_input()
        if raw is None or raw.strip() == "":
            return
        try:
            self.overrides[key] = float(raw.strip())
        except ValueError:
            messagebox.showwarning(
                "Invalid number", f"'{raw}' is not a valid number.")
            return
        self._update_sidebar_stats()
        self._set_status(f"{label.title()} overridden to {raw.strip()} {unit}.")
        self._render()

    def _update_sidebar_stats(self):
        for key, _label, unit, dec in STAT_DEFS:
            val = self._stat_display_value(key)
            if val is None:
                text = f"--  {unit}"
            else:
                text = f"{val:.{dec}f}  {unit}"
            if key in self.overrides:
                text += "  ✎"
            self.stat_value_lbls[key].configure(text=text)

    # ================================================================== #
    #  Rendering
    # ================================================================== #

    def _set_status(self, text):
        self.status_lbl.configure(text=text)

    def _render(self):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        if self.cap is None:
            self.canvas.delete("all")
            self.canvas.create_text(
                cw / 2, ch / 2 - 14, text="OPENTRACK STUDIO",
                fill=TM_ORANGE, font=("Arial", 22, "bold"),
            )
            self.canvas.create_text(
                cw / 2, ch / 2 + 16,
                text="Upload a .mp4 or .mov video to begin",
                fill=FG_MUTED, font=("Arial", 12),
            )
            self._disp = None
            return

        frame = self._compose_frame(self.current_idx)
        if frame is None:
            return

        fh, fw = frame.shape[:2]
        scale = min(cw / fw, ch / fh)
        dw = max(1, int(fw * scale))
        dh = max(1, int(fh * scale))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        disp = cv2.resize(frame, (dw, dh), interpolation=interp)
        disp = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)

        image = Image.fromarray(disp)
        self._photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo)

        ox = (cw - dw) / 2.0
        oy = (ch - dh) / 2.0
        self._disp = (scale, ox, oy, dw, dh)

    def _compose_frame(self, idx):
        """Raw frame + all overlays (markers, calibration, ring, tiles)."""
        raw = self._get_frame(idx)
        if raw is None:
            return None
        frame = raw.copy()
        frame = _rotate_frame(frame, self.rotation)

        self._draw_calibration(frame)
        if self.trajectory is None:
            self._draw_click_markers(frame, idx)
        else:
            if self.show_ring_var.get():
                self._draw_tracking_ring(frame, idx)
            self._draw_stat_tiles(frame, idx)
        return frame

    # ------------------------- overlay pieces ------------------------- #

    def _draw_calibration(self, frame):
        # live drag preview
        if self.mode == MODE_CALIBRATE and self._cal_start is not None \
                and self._cal_current is not None:
            p1 = tuple(int(round(v)) for v in self._cal_start)
            p2 = tuple(int(round(v)) for v in self._cal_current)
            cv2.line(frame, p1, p2, BLACK_BGR, 5, cv2.LINE_AA)
            cv2.line(frame, p1, p2, ORANGE_BGR, 2, cv2.LINE_AA)
            for p in (p1, p2):
                cv2.circle(frame, p, 6, ORANGE_BGR, -1, cv2.LINE_AA)
            length_px = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            mid = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2 - 12)
            cv2.putText(frame, f"{length_px:.0f}px", mid,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE_BGR, 2,
                        cv2.LINE_AA)
        # persisted calibration line (only while in calibrate mode, subtle)
        elif self.mode == MODE_CALIBRATE and self._cal_line is not None:
            p1 = tuple(int(round(v)) for v in self._cal_line[0])
            p2 = tuple(int(round(v)) for v in self._cal_line[1])
            cv2.line(frame, p1, p2, ORANGE_BGR, 1, cv2.LINE_AA)
            for p in (p1, p2):
                cv2.circle(frame, p, 4, ORANGE_BGR, 1, cv2.LINE_AA)

    def _draw_click_markers(self, frame, idx):
        """Show manual marks while the shot is being annotated."""
        r_big = max(8, self.frame_w // 120)

        for i, (f, x, y) in enumerate(self.launch_clicks):
            p = (int(round(x)), int(round(y)))
            on_frame = (f == idx)
            color = ORANGE_BGR if on_frame else (0, 60, 170)
            cv2.drawMarker(frame, p, color, cv2.MARKER_CROSS,
                           r_big * 2, 2 if on_frame else 1, cv2.LINE_AA)
            cv2.putText(frame, str(i + 1), (p[0] + r_big, p[1] - r_big),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        for click, tag in ((self.apex_click, "APEX"),
                           (self.landing_click, "LAND")):
            if click is None:
                continue
            f, x, y = click
            p = (int(round(x)), int(round(y)))
            on_frame = (f == idx)
            color = ORANGE_BGR if on_frame else (0, 60, 170)
            cv2.circle(frame, p, r_big, color, 2, cv2.LINE_AA)
            cv2.putText(frame, tag, (p[0] + r_big + 4, p[1] + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    def _draw_tracking_ring(self, frame, idx):
        """
        Hollow TrackMan-orange ring on the fitted path.

        OFF-FRAME RULE: the math keeps running for every frame of the flight,
        but the ring is only rasterised when it intersects the picture. A ring
        fully outside the frame is skipped entirely (no glitching), a ring
        partially outside is cleanly clipped by OpenCV, and when the path
        re-enters the frame the ring reappears fluidly on its exact position.
        """
        if self.trajectory is None or idx not in self.trajectory:
            return
        x, y = self.trajectory[idx]
        h, w = frame.shape[:2]
        r = max(9, int(round(w / 90.0)))

        # fully outside the frame -> the visual disappears, math continues
        if x + r < 0 or x - r >= w or y + r < 0 or y - r >= h:
            return

        c = (int(round(x)), int(round(y)))
        # dark halo underneath for contrast, then the vibrant orange ring
        cv2.circle(frame, c, r, BLACK_BGR, 5, cv2.LINE_AA)
        cv2.circle(frame, c, r, ORANGE_BGR, 3, cv2.LINE_AA)
        # tiny centre dot, like the broadcast tracer
        if 0 <= c[0] < w and 0 <= c[1] < h:
            cv2.circle(frame, c, 2, WHITE_BGR, -1, cv2.LINE_AA)

    def _draw_stat_tiles(self, frame, idx):
        """Semi-transparent stat tiles that fade in at the apex frame."""
        self._tile_rects = {}
        if self.apex_frame is None or idx < self.apex_frame:
            return

        visible = [(k, lbl, unit, dec) for k, lbl, unit, dec in STAT_DEFS
                   if self.tile_vars[k].get()]
        if not visible:
            return

        h, w = frame.shape[:2]
        n = len(visible)
        gap = max(6, int(w * 0.015))
        tile_w = min(int(w * 0.21), (w - (n + 1) * gap) // max(n, 1))
        tile_w = max(90, tile_w)
        tile_h = int(tile_w * 0.52)
        total_w = n * tile_w + (n - 1) * gap
        x0 = (w - total_w) // 2
        y0 = max(8, int(h * 0.045))

        # fade in over ~10 frames after the apex
        fade = min(1.0, (idx - self.apex_frame + 1) / 10.0)
        alpha = 0.72 * fade

        overlay = frame.copy()
        rects = []
        for i, (key, label, unit, dec) in enumerate(visible):
            x1 = x0 + i * (tile_w + gap)
            y1 = y0
            x2 = x1 + tile_w
            y2 = y1 + tile_h
            rects.append((key, label, unit, dec, x1, y1, x2, y2))
            cv2.rectangle(overlay, (x1, y1), (x2, y2), DARK_BGR, -1)
            # thin orange accent strip on the left edge (TrackMan flavour)
            cv2.rectangle(overlay, (x1, y1), (x1 + max(3, tile_w // 60), y2),
                          ORANGE_BGR, -1)

        cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)

        text_col = tuple(int(c * fade + 0) for c in WHITE_BGR)
        label_col = tuple(int(c * fade) for c in ORANGE_BGR)
        unit_col = tuple(int(c * fade) for c in GREY_BGR)

        for key, label, unit, dec, x1, y1, x2, y2 in rects:
            cx = (x1 + x2) / 2.0
            th = y2 - y1

            # label
            ls = _fit_font_scale(label, th * 0.14,
                                 font=cv2.FONT_HERSHEY_SIMPLEX)
            _put_text_centered(frame, label, cx, y1 + th * 0.24, ls,
                               label_col, 1, font=cv2.FONT_HERSHEY_SIMPLEX)

            # value
            val = self._stat_display_value(key)
            vtext = "--" if val is None else f"{val:.{dec}f}"
            vs = _fit_font_scale(vtext, th * 0.34)
            _put_text_centered(frame, vtext, cx, y1 + th * 0.66, vs,
                               text_col, 2)

            # unit
            us = _fit_font_scale(unit, th * 0.13,
                                 font=cv2.FONT_HERSHEY_SIMPLEX)
            _put_text_centered(frame, unit, cx, y1 + th * 0.90, us,
                               unit_col, 1, font=cv2.FONT_HERSHEY_SIMPLEX)

            # thin border + remember hit-box for double-click editing
            cv2.rectangle(frame, (x1, y1), (x2, y2), (60, 60, 65), 1)
            self._tile_rects[key] = (x1, y1, x2, y2)

    # ================================================================== #
    #  Shutdown
    # ================================================================== #

    def _on_close(self):
        self._stop_play()
        if self.cap is not None:
            self.cap.release()
        self.destroy()


def main():
    app = LaunchMonitorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
