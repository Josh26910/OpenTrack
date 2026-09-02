# Getting OpenTrack Studio onto your iPhone — free, no $99/yr dev account

This app can only be **compiled** by Apple's toolchain (Xcode, macOS-only) —
that part can't be avoided. The trick below is doing that compile step on a
free GitHub-hosted Mac instead of buying one, then installing the result with
**AltStore**, which signs apps with a free Apple ID instead of a paid
Developer Program membership.

## 1. Build the .ipa (free, no Mac needed on your end)

1. Push this repo to GitHub (already done if you're reading this from there).
2. Go to **Actions → "Build iOS (unsigned .ipa for AltStore sideload)"** →
   **Run workflow**. It uses GitHub's free macOS runners.
3. When it finishes (a few minutes), open the run and download the
   **OpenTrackStudio-unsigned-ipa** artifact. Unzip it — you get
   `OpenTrackStudio-unsigned.ipa`.

This build is intentionally unsigned (`CODE_SIGNING_ALLOWED=NO`) — AltStore
does the actual signing itself using your Apple ID during install, so the
build doesn't need any Apple credentials or certificates baked in.

## 2. Install AltServer on your computer

AltServer is the companion app that talks to your iPhone and signs apps with
your free Apple ID. It has Windows, macOS, and (community) Linux builds:

- Windows / macOS: https://altstore.io
- Linux: `AltServer-Linux` from the AltStore GitHub releases

Install it, then plug your iPhone into the same computer (or make sure it's
on the same Wi-Fi network with AltServer's helper running).

## 3. Sideload the app

1. On your computer, open AltServer → **Install AltStore** → select your
   iPhone. Enter your Apple ID + password when prompted (this is a normal
   Apple sign-in used only to request a free developer certificate — no
   payment, no $99/yr program).
2. On your iPhone: **Settings → General → VPN & Device Management** → trust
   the certificate for your Apple ID.
3. Open AltServer's menu again → **Install .ipa** (or drag
   `OpenTrackStudio-unsigned.ipa` onto the AltServer menu bar icon /
   right-click → Install) → pick your iPhone → select the `.ipa` file you
   downloaded in step 1.
4. The app installs and appears on your home screen as **OpenTrack Studio**.

## The catch (same for every free-signed app, not specific to this one)

Apps signed with a **free** Apple ID expire after **7 days** and stop
launching until re-signed. Two ways to handle that:

- Keep AltServer running on your computer with your iPhone reachable over
  Wi-Fi — AltStore refreshes signatures for its installed apps automatically
  in the background roughly every 7 days.
- Or just re-run step 3 manually whenever it expires.

A **paid** Apple Developer account ($99/yr) removes the 7-day limit entirely
— but the whole point of this setup is to skip that cost for testing.

## Local build (if you ever get access to a Mac)

```
cd ios
brew install xcodegen   # one-time
xcodegen generate
open OpenTrackStudio.xcodeproj
```

Then in Xcode: plug in your iPhone, select it as the run destination, set
your Apple ID under Signing & Capabilities (free personal team is fine), and
hit Run. No CI, no AltStore needed in that case — Xcode does the free
7-day signing itself.
