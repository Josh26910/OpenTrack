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
import time
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

# Generous (min, max) plausibility bounds per stat, well outside anything a
# real golf shot can produce (fastest recorded human ball speed is ~225mph,
# longest recorded carries top out well under 450yds). A value outside these
# bounds almost always means a bad calibration or a mis-click, not a real
# shot -- flag it instead of silently displaying it as if it were trustworthy.
STAT_BOUNDS = {
    "ball_speed": (1.0, 230.0),
    "carry": (1.0, 420.0),
    "launch": (-15.0, 60.0),
    "height": (1.0, 220.0),
}

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
        self.fps = 30.0                # true capture fps — used for physics
        self.playback_fps = 30.0       # on-screen playback pacing (slow-mo)
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
        self._play_clock_start = 0.0   # wall-clock time playback started
        self._play_idx_start = 0       # frame index playback started from

        # ---------------- preview window (pre-rendered, no live drawing) ----
        self._preview_win = None
        self._preview_canvas = None
        self._preview_photos = []      # pre-baked PhotoImage per frame
        self._preview_frames = []      # raw video-frame index per entry above
        self._preview_idx = 0          # index into _preview_photos
        self._preview_playing = False
        self._preview_job = None
        self._preview_clock_start = 0.0
        self._preview_idx_start = 0
        self._preview_slider = None
        self._preview_play_btn = None
        self._preview_slider_guard = False
        self._preview_render_state = None   # in-progress chunked render, if any

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
        self.stat_warnings = {}        # {key: True} for implausible values
        self.overrides = {}            # user-typed values from tile edits
        self._tile_rects = {}          # {key: (x1,y1,x2,y2)} video coords

        # ---------------- display transform ----------------
        # (rotated_frame_w, rotated_frame_h) for the image currently placed
        # on the canvas — the ground truth used by _canvas_to_video, paired
        # with a live canvas.bbox() query so clicks always match what's on
        # screen even if window dimensions and event coordinates disagree.
        self._disp_rot_dims = None
        self._photo = None
        self._canvas_image_id = None

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

        # -- playback speed / slow motion -----------------------------------
        fps_row = ctk.CTkFrame(sb, fg_color="transparent")
        fps_row.pack(fill="x", padx=16, pady=(6, 2))
        cap_col = ctk.CTkFrame(fps_row, fg_color="transparent")
        cap_col.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkLabel(
            cap_col, text="Capture FPS", font=ctk.CTkFont(size=10),
            text_color=FG_MUTED, anchor="w",
        ).pack(fill="x")
        self.capture_fps_entry = ctk.CTkEntry(
            cap_col, fg_color=BG_WIDGET, border_color=BORDER,
            text_color=FG_TEXT, height=28,
        )
        self.capture_fps_entry.pack(fill="x")

        play_col = ctk.CTkFrame(fps_row, fg_color="transparent")
        play_col.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ctk.CTkLabel(
            play_col, text="Playback FPS", font=ctk.CTkFont(size=10),
            text_color=FG_MUTED, anchor="w",
        ).pack(fill="x")
        self.playback_fps_entry = ctk.CTkEntry(
            play_col, fg_color=BG_WIDGET, border_color=BORDER,
            text_color=FG_TEXT, height=28,
        )
        self.playback_fps_entry.pack(fill="x")

        ctk.CTkButton(
            sb, text="Apply Speed", height=28,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=BORDER, border_width=1,
            text_color=FG_TEXT, font=ctk.CTkFont(size=11, weight="bold"),
            command=self._apply_fps_settings,
        ).pack(fill="x", padx=16, pady=(4, 2))

        self.slowmo_lbl = ctk.CTkLabel(
            sb, text="", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TM_ORANGE, anchor="w",
        )
        self.slowmo_lbl.pack(fill="x", padx=16, pady=(0, 6))

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
        ).pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkButton(
            sb, text="▶  PREVIEW (SMOOTH PLAYBACK)", height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2,
            border_color=TM_ORANGE, border_width=1, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.open_preview_window,
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
        self.bind("<Left>", lambda e: self.step(-1))
        self.bind("<Right>", lambda e: self.step(1))

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
        # high-speed / slow-mo footage (e.g. a 240fps phone capture) is
        # meant to be studied slowly — default playback to a comfortable
        # 30fps viewing rate whenever the capture rate is well above that,
        # while physics (ball speed, trajectory timing) always uses the
        # true self.fps captured above, never the playback rate.
        self.playback_fps = 30.0 if self.fps > 60.0 else self.fps
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

        self.capture_fps_entry.delete(0, "end")
        self.capture_fps_entry.insert(0, f"{self.fps:g}")
        self.playback_fps_entry.delete(0, "end")
        self.playback_fps_entry.insert(0, f"{self.playback_fps:g}")
        self._update_slowmo_label()

        self._set_status(
            "Video loaded. Calibrate, then step to impact and click the ball.")
        self._render()

    def _update_slowmo_label(self):
        if self.fps <= 0 or self.playback_fps <= 0:
            self.slowmo_lbl.configure(text="")
            return
        factor = self.fps / self.playback_fps
        if factor > 1.02:
            self.slowmo_lbl.configure(text=f"▶ {factor:.1f}× slow motion")
        elif factor < 0.98:
            self.slowmo_lbl.configure(text=f"▶ {1.0 / factor:.1f}× fast forward")
        else:
            self.slowmo_lbl.configure(text="▶ real-time playback")

    def _apply_fps_settings(self):
        if self.cap is None:
            return
        try:
            cap_fps = float(self.capture_fps_entry.get())
            play_fps = float(self.playback_fps_entry.get())
        except ValueError:
            messagebox.showwarning(
                "Invalid FPS", "Capture FPS and Playback FPS must be numbers.")
            return
        if cap_fps <= 0 or play_fps <= 0:
            messagebox.showwarning(
                "Invalid FPS", "FPS values must be greater than zero.")
            return

        self.fps = cap_fps
        self.playback_fps = play_fps
        self._update_slowmo_label()
        self._update_frame_label()
        # physics timing depends on self.fps — refresh any existing track
        if self.trajectory is not None and self.apex_click is not None \
                and self.landing_click is not None and hasattr(self, "_fit_x"):
            try:
                self._fit_trajectory()
                self._compute_stats()
                self._update_sidebar_stats()
            except Exception:                           # noqa: BLE001
                pass
        self._set_status(
            f"Capture rate set to {cap_fps:g} fps, playback set to "
            f"{play_fps:g} fps.")

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
            self._play_clock_start = time.perf_counter()
            self._play_idx_start = self.current_idx
            self._play_tick()

    def _play_tick(self):
        if not self.playing or self.cap is None:
            return
        if self.current_idx >= self.frame_count - 1:
            self._stop_play()
            return

        # Real-time pacing: advance to whichever frame *should* be showing
        # right now given wall-clock time elapsed since play started, rather
        # than blindly stepping by exactly one frame per tick. If rendering
        # ever falls behind (large frames, a slow machine, heavy overlays),
        # this catches up by skipping frames so the overall playback speed
        # stays correct instead of the whole video quietly running in
        # unintended slow motion.
        elapsed = time.perf_counter() - self._play_clock_start
        target_idx = self._play_idx_start + int(round(elapsed * self.playback_fps))
        target_idx = max(self.current_idx + 1, target_idx)
        target_idx = min(target_idx, self.frame_count - 1)
        self.seek(target_idx)

        if self.current_idx >= self.frame_count - 1:
            self._stop_play()
            return

        delay = max(1, int(round(1000.0 / self.playback_fps)))
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

    def _canvas_to_rotated(self, cx, cy):
        """Map a canvas click to pixel coords in the ROTATED (displayed)
        frame's own space (or None).

        Uses the canvas's own live bounding box for the displayed image
        (canvas.bbox) rather than separately-tracked window dimensions, so
        the click coordinate system and the render coordinate system can
        never drift apart (this is what HiDPI / Tk display-scaling desync
        would otherwise cause: winfo_width()/winfo_height() disagreeing
        with the pixel space that mouse events are reported in).
        """
        if self.cap is None or self._disp_rot_dims is None:
            return None
        bbox = self.canvas.bbox("frame_img")
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        dw = x2 - x1
        dh = y2 - y1
        if dw <= 0 or dh <= 0:
            return None
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            return None

        rot_w, rot_h = self._disp_rot_dims
        scale_x = dw / rot_w
        scale_y = dh / rot_h

        rx = (cx - x1) / scale_x
        ry = (cy - y1) / scale_y

        rx = min(max(rx, 0), rot_w - 1)
        ry = min(max(ry, 0), rot_h - 1)
        return (rx, ry)

    def _rotated_to_video(self, rx, ry):
        """Inverse-rotate a point from displayed/rotated space back into
        the original (unrotated) video frame's pixel space."""
        if self.rotation == 0:
            vx, vy = rx, ry
        elif self.rotation == 90:
            vx, vy = ry, self.frame_h - 1 - rx
        elif self.rotation == 180:
            vx, vy = self.frame_w - 1 - rx, self.frame_h - 1 - ry
        elif self.rotation == 270:
            vx, vy = self.frame_w - 1 - ry, rx
        else:
            vx, vy = rx, ry

        vx = min(max(vx, 0), self.frame_w - 1)
        vy = min(max(vy, 0), self.frame_h - 1)
        return (float(vx), float(vy))

    def _video_to_rotated(self, vx, vy):
        """Forward-rotate a point from the original video frame's pixel
        space into the currently displayed/rotated frame's pixel space.
        Inverse of `_rotated_to_video`; used to place overlays (click dots,
        the tracking ring, calibration lines) correctly on a rotated frame.
        """
        if self.rotation == 0:
            return (vx, vy)
        if self.rotation == 90:
            return (self.frame_h - 1 - vy, vx)
        if self.rotation == 180:
            return (self.frame_w - 1 - vx, self.frame_h - 1 - vy)
        if self.rotation == 270:
            return (vy, self.frame_w - 1 - vx)
        return (vx, vy)

    def _canvas_to_video(self, cx, cy):
        """Map a canvas click to video-pixel coordinates in the ORIGINAL
        (unrotated) frame space (or None)."""
        r = self._canvas_to_rotated(cx, cy)
        if r is None:
            return None
        return self._rotated_to_video(r[0], r[1])

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
            self._update_live_preview()
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
            self._update_live_preview()
            self._render()
            return

        if self.mode == MODE_LANDING:
            self._stop_play()
            self.landing_click = (self.current_idx, pt[0], pt[1])
            self.landing_lbl.configure(
                text=f"Landing: frame {self.current_idx}")
            self._set_status(f"Landing marked on frame {self.current_idx}.")
            self._update_live_preview()
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
        # tile rects are stored in rotated/displayed frame space (they're
        # laid out directly from the rotated frame's width/height), so hit
        # testing must use the same rotated-space point, not the
        # original-video-space point that _canvas_to_video returns.
        pt = self._canvas_to_rotated(event.x, event.y)
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

    def _update_live_preview(self):
        """Recompute a lightweight, live tracking path from whatever marks
        currently exist (launch clicks, plus apex/landing if set), so the
        tracking ring follows the ball immediately as the user clicks —
        without waiting for "Track Shot". Piecewise-linear interpolation
        between consecutive marked frames; frames outside the marked range
        (e.g. before impact) intentionally show no ring, since there is no
        click data to base a position on there. Overwritten by the full
        physics-based parabolic fit once "Track Shot" is pressed.
        """
        points = list(self.launch_clicks)
        if self.apex_click is not None:
            points.append(self.apex_click)
        if self.landing_click is not None:
            points.append(self.landing_click)

        # de-duplicate by frame (keep first occurrence) and sort by frame
        seen = set()
        uniq = []
        for p in sorted(points, key=lambda p: p[0]):
            if p[0] not in seen:
                uniq.append(p)
                seen.add(p[0])

        if len(uniq) < 2:
            self.trajectory = None
            return

        frames = [p[0] for p in uniq]
        xs = [p[1] for p in uniq]
        ys = [p[2] for p in uniq]

        f0, f1 = frames[0], frames[-1]
        traj = {}
        for f in range(f0, f1 + 1):
            x = float(np.interp(f, frames, xs))
            y = float(np.interp(f, frames, ys))
            traj[f] = (x, y)
        self.trajectory = traj

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

        # Exit whatever marking mode was active. Leaving the app in, say,
        # "Mark Landing" mode after a successful track meant the canvas
        # stayed in click-to-mark mode straight into playback -- a single
        # stray click while reviewing the shot would silently overwrite
        # the landing point and corrupt the already-computed trajectory
        # with no warning, which looks exactly like "tracking is broken".
        self._set_mode(MODE_IDLE)

        if self.yards_per_px is None:
            self._set_status(
                "Shot tracked — calibrate to unlock real-world numbers, "
                "or double-click the tiles to type your own.")
        elif self.stat_warnings:
            bad = ", ".join(
                lbl for k, lbl, _u, _d in STAT_DEFS if self.stat_warnings.get(k))
            self._set_status(
                f"Shot tracked, but {bad} looks physically implausible — "
                "check your calibration line/distance, or double-click the "
                "tile to type a trusted value.")
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

        # Per-segment display rule, not one global smoothed curve everywhere:
        # between two consecutive marks that are close together in time
        # (< GAP_THRESHOLD frames apart), the user has effectively told us
        # where the ball was for that whole stretch, so just connect their
        # literal clicks directly -- there's no meaningful curvature to
        # capture over a couple of frames anyway, and doing so would let a
        # smoothed curve visibly override real data.
        #
        # Across a *wide* gap (>= GAP_THRESHOLD frames, e.g. the long
        # unclicked stretch from the last launch click up through the apex,
        # or apex down to landing), there's no direct data for those
        # in-between frames at all -- connecting them with a straight line
        # would be flatly wrong for a ball in flight, so that stretch uses
        # the physics-fit parabola's *shape* instead.
        #
        # Wide-gap segments are NOT the global fit's raw curve, and they are
        # not free-solved constant-acceleration arcs either: forcing the
        # clicked velocity *magnitude* onto an arc that must land on the
        # next mark over-constrains it -- when the clicked px/frame speed
        # exceeds what the gap can absorb, the solved "acceleration" flings
        # the ball far past the apex before dragging it back (the ball flew
        # off frame and never descended). Instead each wide gap is built to
        # be *monotone toward its target* on both axes:
        #
        #   * last click -> APEX: vertical motion is a monotone cubic
        #     Hermite that starts at the clicked vertical speed (clamped
        #     into the Fritsch-Carlson monotone region so it can never
        #     overshoot the apex) and arrives with ZERO vertical velocity --
        #     the apex mark is the true peak of the flight;
        #   * APEX -> LANDING: a from-rest gravity parabola,
        #     y = y_apex + (y_land - y_apex) * (tau/T)^2, which leaves the
        #     apex flat (C1 through the peak) and accelerates downward to
        #     hit the landing mark exactly;
        #   * horizontal motion everywhere is a constant-deceleration glide
        #     whose launch speed is the clicked/chained speed clamped into
        #     [0, 2*Dx/T] -- as close to the clicked speed as physics
        #     allows while still guaranteeing forward-only motion that ends
        #     exactly on the mark. The descent chains the ascent's exit
        #     speed, so speed stays continuous through the apex.
        #
        # Net effect: the flight is confined to the box spanned by the
        # marks (it cannot fly off screen), rises to the apex, and descends
        # onto the landing point. Every frame you actually clicked is still
        # set to your exact raw pixel -- never overridden by the curve.
        GAP_THRESHOLD = 5
        V0_TRAIL_POINTS = 4     # regression window for the seam velocity
        V0_TRAIL_SPAN = 12      # ignore trailing clicks older than this many frames

        def monotone_v0(v, D, T):
            # Launch speed for a constant-acceleration axis that must travel
            # D over T frames without ever moving past the target: it has to
            # point toward D and use at most full deceleration-to-rest
            # (2D/T). Anything outside that window guarantees overshoot.
            lo, hi = sorted((0.0, 2.0 * D / T))
            return min(max(v, lo), hi)

        traj = {}
        prev_end_vel = None     # px/frame velocity at the end of the previous segment
        prev_was_curve = False
        for i, ((fa, xa, ya), (fb, xb, yb)) in enumerate(zip(pts, pts[1:])):
            traj[fa] = (xa, ya)
            gap = fb - fa
            if gap < GAP_THRESHOLD:
                if gap >= 1:
                    for f in range(fa + 1, fb):
                        frac = (f - fa) / gap
                        traj[f] = (xa + (xb - xa) * frac,
                                   ya + (yb - ya) * frac)
                    prev_end_vel = ((xb - xa) / gap, (yb - ya) / gap)
                    prev_was_curve = False
                continue

            # seam velocity: chain the previous arc's exit velocity, else a
            # short linear regression over the trailing clicks (regression,
            # not just the last two clicks, so one shaky click can't fling
            # the arc), else fall back to the segment's average velocity
            T = float(gap)
            Dx, Dy = xb - xa, yb - ya
            if prev_was_curve and prev_end_vel is not None:
                v_in = prev_end_vel
            else:
                trail = [(f, x, y) for (f, x, y) in pts[:i + 1]
                         if fa - f <= V0_TRAIL_SPAN][-V0_TRAIL_POINTS:]
                if len(trail) >= 2:
                    tf = np.array([p[0] for p in trail], dtype=float)
                    v_in = (np.polyfit(tf, [p[1] for p in trail], 1)[0],
                            np.polyfit(tf, [p[2] for p in trail], 1)[0])
                elif prev_end_vel is not None:
                    v_in = prev_end_vel
                else:
                    v_in = (Dx / T, Dy / T)

            # horizontal: clamped constant-deceleration glide onto the mark
            v0x = monotone_v0(v_in[0], Dx, T)
            sax = 2.0 * (Dx - v0x * T) / (T * T)

            ends_at_apex = (i + 1 == n_launch)
            starts_at_apex = (i == n_launch)
            if starts_at_apex:
                # descent: from rest at the apex, fall onto the landing mark
                vy_end = 2.0 * Dy / T
            elif ends_at_apex:
                # ascent: monotone cubic Hermite, zero slope at the apex
                lo, hi = sorted((0.0, 3.0 * Dy / T))
                m0y = min(max(v_in[1], lo), hi)
                vy_end = 0.0
            else:
                # wide gap between launch clicks: same clamped glide as x
                v0y = monotone_v0(v_in[1], Dy, T)
                say = 2.0 * (Dy - v0y * T) / (T * T)
                vy_end = v0y + say * T

            for f in range(fa + 1, fb):
                tau = f - fa
                x = xa + v0x * tau + 0.5 * sax * tau * tau
                if starts_at_apex:
                    y = ya + Dy * (tau / T) ** 2
                elif ends_at_apex:
                    s = tau / T
                    h00 = (2.0 * s - 3.0) * s * s + 1.0
                    h10 = ((s - 2.0) * s + 1.0) * s
                    y = h00 * ya + (1.0 - h00) * yb + h10 * T * m0y
                else:
                    y = ya + v0y * tau + 0.5 * say * tau * tau
                traj[f] = (x, y)
            prev_end_vel = (v0x + sax * T, vy_end)
            prev_was_curve = True
        traj[pts[-1][0]] = (pts[-1][1], pts[-1][2])

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
        self.stat_warnings = {
            key: not (lo <= val <= hi)
            for key, val in stats.items()
            if val is not None
            for lo, hi in [STAT_BOUNDS[key]]
        }

    def clear_marks(self, silent=False):
        self.launch_clicks = []
        self.apex_click = None
        self.landing_click = None
        self.trajectory = None
        self.impact_frame = None
        self.apex_frame = None
        self.landing_frame = None
        self.stats = {}
        self.stat_warnings = {}
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

    def _stat_is_warning(self, key):
        """True if the currently-displayed value is a computed number that
        fell outside a physically-plausible range (see STAT_BOUNDS) -- a
        strong signal of a bad calibration or a mis-click rather than a
        real shot. A manual override always clears the warning, since at
        that point the user is vouching for the number themselves."""
        if key in self.overrides:
            return False
        return self.stat_warnings.get(key, False)

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
            elif self._stat_is_warning(key):
                text += "  ⚠"
            self.stat_value_lbls[key].configure(
                text=text,
                text_color=TM_ORANGE if self._stat_is_warning(key) else FG_TEXT,
            )

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
            self._canvas_image_id = None
            self.canvas.create_text(
                cw / 2, ch / 2 - 14, text="OPENTRACK STUDIO",
                fill=TM_ORANGE, font=("Arial", 22, "bold"),
            )
            self.canvas.create_text(
                cw / 2, ch / 2 + 16,
                text="Upload a .mp4 or .mov video to begin",
                fill=FG_MUTED, font=("Arial", 12),
            )
            self._disp_rot_dims = None
            return

        frame = self._compose_frame(self.current_idx,
                                    show_marks=not self.playing)
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

        # Reuse the same canvas image item across frames instead of tearing
        # down and rebuilding the whole canvas item tree every tick — with
        # playback ticking dozens of times per second, that rebuild cost was
        # a real contributor to frames falling behind their target pace.
        if self._canvas_image_id is None:
            self.canvas.delete("all")
            self._canvas_image_id = self.canvas.create_image(
                cw // 2, ch // 2, image=self._photo, tags="frame_img")
        else:
            self.canvas.itemconfig(self._canvas_image_id, image=self._photo)
            self.canvas.coords(self._canvas_image_id, cw // 2, ch // 2)

        # dimensions of the (possibly rotated) frame that was just resized
        # and placed on the canvas — used by _canvas_to_video to convert
        # click positions back into video-pixel space.
        self._disp_rot_dims = (fw, fh)

    def _compose_frame(self, idx, show_marks=True):
        """Raw frame + all overlays (markers, calibration, ring, tiles)."""
        raw = self._get_frame(idx)
        if raw is None:
            return None
        frame = raw.copy()
        frame = _rotate_frame(frame, self.rotation)

        self._draw_calibration(frame)
        # The numbered reference dots are annotation-time UI only. During
        # playback on the main canvas and in the baked Preview window they
        # are suppressed (show_marks=False) so the tracking ring flies
        # clean instead of flashing over the manually clicked dots.
        if show_marks:
            self._draw_click_markers(frame, idx)
        if self.trajectory is not None:
            if self.show_ring_var.get():
                self._draw_tracking_ring(frame, idx)
            self._draw_stat_tiles(frame, idx)
        return frame

    # ------------------------- overlay pieces ------------------------- #

    def _draw_calibration(self, frame):
        # live drag preview
        if self.mode == MODE_CALIBRATE and self._cal_start is not None \
                and self._cal_current is not None:
            p1r = self._video_to_rotated(*self._cal_start)
            p2r = self._video_to_rotated(*self._cal_current)
            p1 = tuple(int(round(v)) for v in p1r)
            p2 = tuple(int(round(v)) for v in p2r)
            cv2.line(frame, p1, p2, BLACK_BGR, 5, cv2.LINE_AA)
            cv2.line(frame, p1, p2, ORANGE_BGR, 2, cv2.LINE_AA)
            for p in (p1, p2):
                cv2.circle(frame, p, 6, ORANGE_BGR, -1, cv2.LINE_AA)
            # real-world (unrotated) pixel distance, not the on-screen one
            length_px = math.hypot(self._cal_current[0] - self._cal_start[0],
                                   self._cal_current[1] - self._cal_start[1])
            mid = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2 - 12)
            cv2.putText(frame, f"{length_px:.0f}px", mid,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE_BGR, 2,
                        cv2.LINE_AA)
        # persisted calibration line (only while in calibrate mode, subtle)
        elif self.mode == MODE_CALIBRATE and self._cal_line is not None:
            p1r = self._video_to_rotated(*self._cal_line[0])
            p2r = self._video_to_rotated(*self._cal_line[1])
            p1 = tuple(int(round(v)) for v in p1r)
            p2 = tuple(int(round(v)) for v in p2r)
            cv2.line(frame, p1, p2, ORANGE_BGR, 1, cv2.LINE_AA)
            for p in (p1, p2):
                cv2.circle(frame, p, 4, ORANGE_BGR, 1, cv2.LINE_AA)

    def _draw_click_markers(self, frame, idx):
        """Show manual marks while the shot is being annotated.

        Only the marker for the CURRENT frame is drawn at "ball size" (a
        prominent ring, matching the tracking ring's look, since on its own
        frame a click is by definition exactly on the ball). Every other
        click is a small, dim reference pip + number — enough to see your
        click history while scrubbing, but never big or bright enough to
        read as a second "ball" floating disconnected from the real one.
        """
        r_dot = max(6, self.frame_w // 140)
        r_halo = r_dot + 3
        r_pip = max(2, r_dot // 3)

        def draw_mark(p, label, on_frame):
            if on_frame:
                cv2.circle(frame, p, r_halo, BLACK_BGR, r_halo // 2, cv2.LINE_AA)
                cv2.circle(frame, p, r_dot, ORANGE_BGR, -1, cv2.LINE_AA)
                cv2.circle(frame, p, r_dot, WHITE_BGR, 1, cv2.LINE_AA)
                cv2.putText(frame, label, (p[0] + r_dot + 6, p[1] + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, ORANGE_BGR, 2,
                            cv2.LINE_AA)
            else:
                cv2.circle(frame, p, r_pip, (90, 110, 130), -1, cv2.LINE_AA)
                cv2.putText(frame, label, (p[0] + r_pip + 5, p[1] + 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (110, 130, 150), 1,
                            cv2.LINE_AA)

        for i, (f, x, y) in enumerate(self.launch_clicks):
            rx, ry = self._video_to_rotated(x, y)
            p = (int(round(rx)), int(round(ry)))
            draw_mark(p, str(i + 1), f == idx)

        for click, tag in ((self.apex_click, "APEX"),
                           (self.landing_click, "LAND")):
            if click is None:
                continue
            f, x, y = click
            rx, ry = self._video_to_rotated(x, y)
            p = (int(round(rx)), int(round(ry)))
            draw_mark(p, tag, f == idx)

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
        vx, vy = self.trajectory[idx]
        x, y = self._video_to_rotated(vx, vy)
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

        # Blend only the small region the tiles actually occupy, not the
        # whole frame. frame.copy() + addWeighted over a full 1080x1920
        # image costs ~3ms/frame on its own -- multiplied by every tick of
        # playback that's a real, measurable contributor to dropped frames
        # and stutter. Restricting both the copy and the blend to the
        # tiles' bounding box cuts that to a fraction of a millisecond
        # (~5x faster in local benchmarking) with identical visual output.
        roi_x1, roi_y1 = x0, y0
        roi_x2, roi_y2 = x0 + total_w, y0 + tile_h
        roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        sub_overlay = roi.copy()

        rects = []
        for i, (key, label, unit, dec) in enumerate(visible):
            x1 = i * (tile_w + gap)
            y1 = 0
            x2 = x1 + tile_w
            y2 = tile_h
            rects.append((key, label, unit, dec,
                          x1 + roi_x1, y1 + roi_y1, x2 + roi_x1, y2 + roi_y1))
            cv2.rectangle(sub_overlay, (x1, y1), (x2, y2), DARK_BGR, -1)
            # thin orange accent strip on the left edge (TrackMan flavour)
            cv2.rectangle(sub_overlay, (x1, y1), (x1 + max(3, tile_w // 60), y2),
                          ORANGE_BGR, -1)

        cv2.addWeighted(sub_overlay, alpha, roi, 1.0 - alpha, 0, roi)

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

            # implausible-value badge: a physically impossible number (bad
            # calibration / mis-click) should never look identical to a
            # trustworthy one, so flag it right on the tile, not just in
            # the sidebar.
            if self._stat_is_warning(key):
                warn_r = max(6, int(th * 0.11))
                warn_c = (x2 - warn_r - 4, y1 + warn_r + 4)
                warn_col = tuple(int(c * fade) for c in (0, 200, 255))
                cv2.circle(frame, warn_c, warn_r, warn_col, -1, cv2.LINE_AA)
                cv2.putText(frame, "!",
                           (warn_c[0] - int(warn_r * 0.28),
                            warn_c[1] + int(warn_r * 0.38)),
                           cv2.FONT_HERSHEY_SIMPLEX, warn_r * 0.045,
                           DARK_BGR, 2, cv2.LINE_AA)

            # thin border + remember hit-box for double-click editing
            cv2.rectangle(frame, (x1, y1), (x2, y2), (60, 60, 65), 1)
            self._tile_rects[key] = (x1, y1, x2, y2)

    # ================================================================== #
    #  Preview window — pre-rendered, no per-frame overlay drawing
    # ================================================================== #
    #
    # The main canvas redraws every overlay (markers, ring, tiles) from
    # scratch on every tick via OpenCV, then hands a brand new PhotoImage
    # to Tk. Tk's Canvas/PhotoImage path was never built for real-time
    # video — even after trimming the per-frame CV cost, the Tk-side image
    # upload alone caps out well under real playback rates on typical
    # hardware. Rather than keep chasing that ceiling, Preview sidesteps it:
    # every frame in the shot's range is composited and converted to a
    # PhotoImage *once*, up front, into a plain Python list. The playback
    # loop in the preview window then does nothing but swap which already-
    # built PhotoImage is showing — no OpenCV, no compositing, no per-frame
    # allocation — so it can actually keep pace with real frame rates.

    # Hard caps on the preview's memory footprint. Pre-baking frames as full
    # PhotoImages is what makes playback smooth, but it means every preview
    # frame is fully decoded and resident in RAM at once for the whole
    # session -- at the old caps (600 frames, 1000px) that's up to ~1.8GB of
    # raw pixel data before Tk's own PhotoImage storage overhead on top,
    # easily enough to make a laptop with 8-16GB of RAM start swapping,
    # which looks and feels exactly like a freeze. At these caps the same
    # worst case is under ~200MB.
    PREVIEW_MAX_FRAMES = 300
    PREVIEW_MAX_DIM = 640

    def open_preview_window(self):
        if self.cap is None:
            messagebox.showwarning("No video", "Load a video first.")
            return
        if self.trajectory is None:
            messagebox.showwarning(
                "Nothing to preview",
                "Mark at least two points (or press Track Shot) before "
                "opening the preview.",
            )
            return

        self._close_preview_window()

        # cover the tracked range plus a little breathing room on each end,
        # capped so pre-render time/memory stay bounded regardless of how
        # long the source video is.
        tracked_frames = list(self.trajectory.keys())
        f0 = min(tracked_frames)
        f1 = max(tracked_frames)
        pad = max(5, int(self.fps * 0.3))
        f0 = max(0, f0 - pad)
        f1 = min(self.frame_count - 1, f1 + pad)

        if f1 - f0 + 1 > self.PREVIEW_MAX_FRAMES:
            f1 = f0 + self.PREVIEW_MAX_FRAMES - 1

        # target display size: fit within most of the screen, capped so a
        # huge source video doesn't blow up pre-render time/memory, always
        # preserving the (rotated) frame's aspect ratio.
        if self.rotation in (90, 270):
            src_w, src_h = self.frame_h, self.frame_w
        else:
            src_w, src_h = self.frame_w, self.frame_h
        max_w = min(self.PREVIEW_MAX_DIM, int(self.winfo_screenwidth() * 0.85))
        max_h = min(self.PREVIEW_MAX_DIM, int(self.winfo_screenheight() * 0.85))
        scale = min(max_w / src_w, max_h / src_h, 1.0)
        target_w = max(1, int(src_w * scale))
        target_h = max(1, int(src_h * scale))

        self._start_preview_render(f0, f1, target_w, target_h)

    def _start_preview_render(self, f0, f1, target_w, target_h):
        """Kick off a chunked, non-blocking render of every frame in
        [f0, f1]. Composited in small batches via self.after() rather than
        one long Python loop -- a single blocking loop over a few hundred
        frames can easily run 5-15+ seconds on a modest laptop CPU, and for
        that whole span Tk never returns to its event loop, so the OS marks
        the window as "Not Responding": a real freeze, not just a slow
        operation. Yielding back to after() every few frames keeps the app
        responsive (and cancellable) throughout, even though the total
        wall-clock time to finish is about the same.
        """
        total = f1 - f0 + 1
        progress = ctk.CTkToplevel(self)
        progress.title("Rendering preview…")
        progress.geometry("360x130")
        progress.configure(fg_color=BG_PANEL)
        progress.transient(self)
        progress.grab_set()
        progress.resizable(False, False)
        ctk.CTkLabel(
            progress, text="Baking a smooth, glitch-free preview…",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=FG_TEXT,
        ).pack(pady=(18, 6))
        bar = ctk.CTkProgressBar(
            progress, progress_color=TM_ORANGE, fg_color=BG_WIDGET, width=300,
        )
        bar.set(0)
        bar.pack(pady=(0, 8))
        status_lbl = ctk.CTkLabel(
            progress, text=f"0 / {total} frames",
            font=ctk.CTkFont(size=11), text_color=FG_MUTED,
        )
        status_lbl.pack(pady=(0, 8))

        state = {
            "f0": f0, "total": total, "i": 0,
            "target_w": target_w, "target_h": target_h,
            "photos": [], "frames": [], "cancelled": False,
            "dialog": progress, "bar": bar, "status_lbl": status_lbl,
            "interp": cv2.INTER_AREA if target_w < self.frame_w else cv2.INTER_LINEAR,
        }

        def cancel():
            state["cancelled"] = True

        ctk.CTkButton(
            progress, text="Cancel", height=28, width=100,
            fg_color=BG_WIDGET, hover_color="#3A2020",
            border_color=BORDER, border_width=1, text_color=FG_TEXT,
            font=ctk.CTkFont(size=12), command=cancel,
        ).pack()
        progress.protocol("WM_DELETE_WINDOW", cancel)

        self._preview_render_state = state
        self._preview_render_step()

    def _preview_render_step(self):
        st = self._preview_render_state
        if st["cancelled"]:
            st["dialog"].grab_release()
            st["dialog"].destroy()
            self._set_status("Preview cancelled.")
            return

        CHUNK = 4  # small enough that each step stays imperceptibly short
        end = min(st["i"] + CHUNK, st["total"])
        for i in range(st["i"], end):
            f = st["f0"] + i
            composed = self._compose_frame(f, show_marks=False)
            if composed is not None:
                disp = cv2.resize(composed, (st["target_w"], st["target_h"]),
                                  interpolation=st["interp"])
                disp = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
                st["photos"].append(ImageTk.PhotoImage(Image.fromarray(disp)))
                st["frames"].append(f)
        st["i"] = end
        st["bar"].set(st["i"] / st["total"])
        st["status_lbl"].configure(text=f"{st['i']} / {st['total']} frames")

        if st["i"] < st["total"]:
            self._preview_job = self.after(1, self._preview_render_step)
            return

        st["dialog"].grab_release()
        st["dialog"].destroy()
        self._preview_job = None

        self._preview_photos = st["photos"]
        self._preview_frames = st["frames"]
        if not self._preview_photos:
            messagebox.showerror("Preview failed", "No frames could be rendered.")
            return
        self._build_preview_window(st["target_w"], st["target_h"])

    def _build_preview_window(self, target_w, target_h):
        win = ctk.CTkToplevel(self)
        win.title("OpenTrack Studio — Preview")
        win.configure(fg_color=BG_ROOT)
        win.geometry(f"{target_w}x{target_h + 90}")
        win.protocol("WM_DELETE_WINDOW", self._close_preview_window)
        self._preview_win = win

        canvas = tk.Canvas(win, width=target_w, height=target_h,
                           bg=BG_ROOT, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True, padx=0, pady=0)
        self._preview_canvas = canvas
        self._preview_image_id = canvas.create_image(
            target_w // 2, target_h // 2, image=self._preview_photos[0])

        bar = ctk.CTkFrame(win, fg_color=BG_PANEL, height=80, corner_radius=0)
        bar.pack(fill="x", side="bottom")

        btn_row = ctk.CTkFrame(bar, fg_color="transparent")
        btn_row.pack(pady=(8, 2))
        self._preview_play_btn = ctk.CTkButton(
            btn_row, text="▶", width=56, height=34,
            fg_color=TM_ORANGE, hover_color=TM_ORANGE_DARK,
            text_color="#000000", font=ctk.CTkFont(size=14, weight="bold"),
            command=self._preview_toggle_play,
        )
        self._preview_play_btn.pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="⏮", width=44, height=34,
            fg_color=BG_WIDGET, hover_color=BG_PANEL_2, text_color=FG_TEXT,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self._preview_seek(0),
        ).pack(side="left", padx=4)

        n = len(self._preview_photos)
        self._preview_slider = ctk.CTkSlider(
            bar, from_=0, to=max(0, n - 1), number_of_steps=max(1, n - 1),
            command=self._preview_on_slider,
            progress_color=TM_ORANGE, button_color=TM_ORANGE,
            button_hover_color="#FF7A30", fg_color=BG_WIDGET, height=16,
        )
        self._preview_slider.set(0)
        self._preview_slider.pack(fill="x", padx=16, pady=(0, 8))

        win.bind("<space>", lambda e: self._preview_toggle_play())
        win.bind("<Left>", lambda e: self._preview_seek(self._preview_idx - 1))
        win.bind("<Right>", lambda e: self._preview_seek(self._preview_idx + 1))
        win.focus_set()

        self._preview_idx = 0
        self._preview_playing = True
        self._preview_clock_start = time.perf_counter()
        self._preview_idx_start = 0
        self._preview_tick()

    def _preview_toggle_play(self):
        if not self._preview_photos:
            return
        if self._preview_playing:
            self._preview_playing = False
            self._preview_play_btn.configure(text="▶")
            if self._preview_job is not None:
                try:
                    self.after_cancel(self._preview_job)
                except Exception:
                    pass
                self._preview_job = None
        else:
            if self._preview_idx >= len(self._preview_photos) - 1:
                self._preview_seek(0)
            self._preview_playing = True
            self._preview_play_btn.configure(text="❚❚")
            self._preview_clock_start = time.perf_counter()
            self._preview_idx_start = self._preview_idx
            self._preview_tick()

    def _preview_tick(self):
        if not self._preview_playing or not self._preview_photos:
            return
        n = len(self._preview_photos)
        if self._preview_idx >= n - 1:
            self._preview_toggle_play()
            return

        elapsed = time.perf_counter() - self._preview_clock_start
        target = self._preview_idx_start + int(round(elapsed * self.playback_fps))
        target = max(self._preview_idx + 1, target)
        target = min(target, n - 1)
        self._preview_show(target)

        if self._preview_idx >= n - 1:
            self._preview_toggle_play()
            return

        delay = max(1, int(round(1000.0 / self.playback_fps)))
        self._preview_job = self.after(delay, self._preview_tick)

    def _preview_show(self, idx):
        if not self._preview_photos:
            return
        idx = max(0, min(idx, len(self._preview_photos) - 1))
        self._preview_idx = idx
        self._preview_canvas.itemconfig(
            self._preview_image_id, image=self._preview_photos[idx])
        self._preview_slider_guard = True
        self._preview_slider.set(idx)
        self._preview_slider_guard = False

    def _preview_seek(self, idx):
        self._preview_playing = False
        if self._preview_play_btn is not None:
            self._preview_play_btn.configure(text="▶")
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
            self._preview_job = None
        self._preview_show(idx)

    def _preview_on_slider(self, value):
        if self._preview_slider_guard:
            return
        self._preview_seek(int(round(float(value))))

    def _close_preview_window(self):
        self._preview_playing = False
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
            self._preview_job = None
        # cancel and tear down an in-progress chunked render, if any
        if self._preview_render_state is not None:
            self._preview_render_state["cancelled"] = True
            dialog = self._preview_render_state.get("dialog")
            if dialog is not None:
                try:
                    dialog.grab_release()
                    dialog.destroy()
                except Exception:
                    pass
            self._preview_render_state = None
        if self._preview_win is not None:
            try:
                self._preview_win.destroy()
            except Exception:
                pass
        self._preview_win = None
        self._preview_canvas = None
        self._preview_photos = []
        self._preview_frames = []

    # ================================================================== #
    #  Shutdown
    # ================================================================== #

    def _on_close(self):
        self._stop_play()
        self._close_preview_window()
        if self.cap is not None:
            self.cap.release()
        self.destroy()


def main():
    app = LaunchMonitorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
