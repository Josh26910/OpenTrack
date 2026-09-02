# OpenTrack

TrackMan-inspired golf launch monitor video editor: load a swing video,
calibrate on a known distance, click the ball through launch/apex/landing,
and get a physics-fit trajectory trace with ball speed, carry, launch angle
and apex height overlaid on the footage.

This repo has three versions of the same idea:

## Web app (`index.html`) — runs on Replit

Single-file HTML/JS/Tailwind app, no build step, no backend. Click **Run**
in Replit (or anywhere: `python3 -m http.server` and open the page) and
it's live — works on desktop or mobile browsers, including "Add to Home
Screen" for a near-native feel on a phone.

## Desktop app (`launch_monitor_editor_10_5.py`)

Python + tkinter/customtkinter + OpenCV. `pip install customtkinter
opencv-python numpy scipy Pillow`, then `python launch_monitor_editor_10_5.py`.

## iOS app (`ios/`)

Native SwiftUI rewrite with feature parity to the desktop editor. Building
it requires Xcode (macOS-only); see `ios/SIDELOAD.md` for a free path to a
signed build via GitHub Actions + AltStore, with no $99/yr Apple Developer
account needed.
