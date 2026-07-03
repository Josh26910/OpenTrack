import SwiftUI
import PhotosUI

struct ContentView: View {
    @StateObject private var video = VideoController()
    @StateObject private var marks = ShotMarks()

    @State private var mode: MarkMode = .idle
    @State private var showRing = true
    @State private var visibleTiles: Set<StatKey> = Set(StatKey.allCases)

    // calibration drag, held in ORIGINAL (unrotated) video pixel space
    @State private var calStart: CGPoint?
    @State private var calCurrent: CGPoint?
    @State private var calibrationDistanceText = ""
    @State private var calibrationUnit: DistanceUnit = .yards
    @State private var pendingCalLine: (CGPoint, CGPoint)?
    @State private var showCalibrationDialog = false
    @State private var calibrationDialogText = ""

    @State private var photoItem: PhotosPickerItem?
    @State private var statusText = "Load a video to begin."
    @State private var showDrawer = false
    @State private var tileRects: [StatKey: CGRect] = [:]

    @State private var editingStat: StatKey?
    @State private var editValueText = ""

    var body: some View {
        ZStack {
            Theme.bgRoot.ignoresSafeArea()
            Theme.backdropGradient.ignoresSafeArea()

            VStack(spacing: 0) {
                header
                stageArea
                TransportBar(video: video, statusText: statusText)
            }
        }
        .sheet(isPresented: $showDrawer) {
            ControlsDrawer(
                video: video, marks: marks, mode: $mode, showRing: $showRing,
                visibleTiles: $visibleTiles, calibrationDistanceText: $calibrationDistanceText,
                calibrationUnit: $calibrationUnit, photoItem: $photoItem,
                onTrack: trackShot, onClear: clearMarks,
                onEditStat: { key in beginEdit(key) }
            )
            .presentationDetents([.medium, .large])
        }
        .onChange(of: photoItem) { _, newItem in
            guard let newItem else { return }
            Task { await importVideo(newItem) }
        }
        .alert("Calibration distance", isPresented: $showCalibrationDialog) {
            TextField("e.g. 45", text: $calibrationDialogText).keyboardType(.decimalPad)
            Button("Cancel", role: .cancel) { pendingCalLine = nil }
            Button("Set") { commitCalibration() }
        } message: {
            Text("Enter the real-world length of the line you drew, in \(calibrationUnit.rawValue).")
        }
        .alert(editingStat?.label.capitalized ?? "Override value", isPresented: Binding(
            get: { editingStat != nil }, set: { if !$0 { editingStat = nil } }
        )) {
            TextField("Value", text: $editValueText).keyboardType(.decimalPad)
            Button("Cancel", role: .cancel) {}
            Button("Set") { commitEdit() }
            if let key = editingStat, marks.overrides[key] != nil {
                Button("Clear override", role: .destructive) {
                    marks.overrides.removeValue(forKey: key)
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    // MARK: - Header

    private var header: some View {
        HStack {
            HStack(spacing: 2) {
                Text("OPEN").font(.title3.weight(.black)).foregroundColor(Theme.textPrimary)
                Text("TRACK").font(.title3.weight(.black)).foregroundColor(Theme.orange)
            }
            Spacer()
            Circle().fill(video.isLoaded ? Theme.green : Theme.textMuted2).frame(width: 8, height: 8)
            Text(video.isLoaded ? "LOADED" : "IDLE").font(.caption2.monospaced()).foregroundColor(Theme.textMuted)
            Button { showDrawer = true } label: {
                Image(systemName: "slider.horizontal.3")
                    .padding(8)
                    .background(Theme.bgWidget)
                    .foregroundColor(Theme.textPrimary)
                    .cornerRadius(8)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Theme.bgPanel)
    }

    // MARK: - Video stage

    private var stageArea: some View {
        GeometryReader { geo in
            let avail = geo.size
            let disp = video.displaySize
            let scale: CGFloat = video.isLoaded
                ? min(avail.width / max(disp.width, 1), avail.height / max(disp.height, 1))
                : 1
            let dispW = disp.width * scale
            let dispH = disp.height * scale
            let rawW = video.naturalSize.width * scale
            let rawH = video.naturalSize.height * scale

            ZStack {
                if video.isLoaded {
                    ZStack {
                        PlayerLayerView(player: video.player)
                            .frame(width: rawW, height: rawH)
                            .rotationEffect(.degrees(Double(video.rotationDegrees)))
                            .frame(width: dispW, height: dispH)

                        VideoOverlayView(
                            video: video, marks: marks, mode: mode, scale: scale,
                            showRing: showRing, visibleTiles: visibleTiles,
                            calStart: calStart, calCurrent: calCurrent, tileRects: $tileRects
                        )
                        .frame(width: dispW, height: dispH)
                    }
                    .frame(width: dispW, height: dispH)
                    .contentShape(Rectangle())
                    .gesture(stageGesture(scale: scale))
                } else {
                    VStack(spacing: 6) {
                        Text("OPENTRACK STUDIO").font(.headline.bold()).foregroundColor(Theme.orange)
                        Text("Choose a video to begin").font(.subheadline).foregroundColor(Theme.textMuted)
                        Button { showDrawer = true } label: {
                            Label("Choose Video", systemImage: "square.and.arrow.up")
                        }
                        .buttonStyle(.primaryTM)
                        .padding(.top, 8)
                    }
                }
            }
            .frame(width: avail.width, height: avail.height)
        }
        .padding(8)
    }

    private func stageGesture(scale: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                guard mode == .calibrate else { return }
                let rotatedPt = CGPoint(x: value.location.x / scale, y: value.location.y / scale)
                let videoPt = video.rotatedToVideo(rotatedPt)
                if calStart == nil { calStart = videoPt }
                calCurrent = videoPt
            }
            .onEnded { value in
                if let key = hitTileKey(at: value.location) {
                    beginEdit(key)
                    return
                }
                let rotatedPt = CGPoint(x: value.location.x / scale, y: value.location.y / scale)
                let videoPt = video.rotatedToVideo(rotatedPt)
                switch mode {
                case .calibrate: finishCalibrationDrag()
                case .launch: recordLaunchClick(videoPt)
                case .apex: recordApex(videoPt)
                case .landing: recordLanding(videoPt)
                case .idle: break
                }
            }
    }

    private func hitTileKey(at point: CGPoint) -> StatKey? {
        guard let apexFrame = marks.apexFrame, video.currentFrame >= apexFrame else { return nil }
        return tileRects.first(where: { $0.value.contains(point) })?.key
    }

    // MARK: - Video import

    private func importVideo(_ item: PhotosPickerItem) async {
        do {
            guard let transferred = try await item.loadTransferable(type: VideoTransferable.self) else { return }
            await video.load(url: transferred.url)
            marks.reset()
            marks.resetCalibration()
            mode = .idle
            statusText = "Video loaded. Calibrate, then step to impact and click the ball."
            showDrawer = false
        } catch {
            statusText = "Could not load that video: \(error.localizedDescription)"
        }
    }

    // MARK: - Marking

    private func recordLaunchClick(_ p: CGPoint) {
        video.pause()
        marks.launchClicks.append(FrameClick(frame: video.currentFrame, point: p))
        marks.launchClicks.sort { $0.frame < $1.frame }
        marks.updateLivePreviewTrajectory()
        statusText = "Launch click \(marks.launchClicks.count) recorded on frame \(video.currentFrame)."
        if video.currentFrame < video.frameCount - 1 { video.seek(toFrame: video.currentFrame + 1) }
    }

    private func recordApex(_ p: CGPoint) {
        video.pause()
        marks.apexClick = FrameClick(frame: video.currentFrame, point: p)
        marks.updateLivePreviewTrajectory()
        statusText = "Apex marked on frame \(video.currentFrame)."
    }

    private func recordLanding(_ p: CGPoint) {
        video.pause()
        marks.landingClick = FrameClick(frame: video.currentFrame, point: p)
        marks.updateLivePreviewTrajectory()
        statusText = "Landing marked on frame \(video.currentFrame)."
    }

    // MARK: - Calibration

    private func finishCalibrationDrag() {
        defer { calStart = nil; calCurrent = nil }
        guard let s = calStart, let c = calCurrent else { return }
        let lengthPx = hypot(c.x - s.x, c.y - s.y)
        guard lengthPx >= 5 else {
            statusText = "Calibration line too short — drag a longer line."
            return
        }
        pendingCalLine = (s, c)
        if let value = Double(calibrationDistanceText), value > 0 {
            applyCalibration(lengthPx: lengthPx, value: value)
        } else {
            calibrationDialogText = ""
            showCalibrationDialog = true
        }
    }

    private func commitCalibration() {
        guard let (s, c) = pendingCalLine else { return }
        let lengthPx = hypot(c.x - s.x, c.y - s.y)
        guard let value = Double(calibrationDialogText), value > 0 else {
            statusText = "Calibration cancelled — no valid distance."
            pendingCalLine = nil
            return
        }
        applyCalibration(lengthPx: lengthPx, value: value)
    }

    private func applyCalibration(lengthPx: CGFloat, value: Double) {
        guard let line = pendingCalLine else { return }
        let yards = value * calibrationUnit.toYards
        marks.yardsPerPixel = yards / Double(lengthPx)
        marks.calibrationLine = line
        pendingCalLine = nil
        mode = .idle
        if !marks.trajectory.isEmpty { recomputeStats() }
        statusText = "Calibration saved."
    }

    // MARK: - Track / clear

    private func trackShot() {
        guard marks.launchClicks.count >= 3 else {
            statusText = "Click the ball on at least 3 frames starting at impact."
            return
        }
        guard let apex = marks.apexClick, let landing = marks.landingClick else {
            statusText = "Mark both the Apex and the Landing Point before tracking."
            return
        }
        let f0 = marks.launchClicks[0].frame
        let fLastLaunch = marks.launchClicks.last!.frame
        guard f0 < apex.frame, apex.frame < landing.frame, apex.frame > fLastLaunch else {
            statusText = "Frames must be ordered: launch clicks → apex → landing."
            return
        }

        let result = TrajectoryFit.fit(launchClicks: marks.launchClicks, apex: apex, landing: landing, fps: video.fps)
        marks.trajectory = result.trajectory
        marks.fitX = result.fitX
        marks.fitY = result.fitY
        marks.impactFrame = result.impactFrame
        marks.apexFrame = result.apexFrame
        marks.landingFrame = result.landingFrame
        recomputeStats()
        mode = .idle

        if marks.yardsPerPixel == nil {
            statusText = "Shot tracked — calibrate for real-world numbers, or tap a tile to type your own."
        } else if !marks.warnings.isEmpty {
            statusText = "Shot tracked, but some values look implausible — check calibration or override."
        } else {
            statusText = "Shot tracked. Press play to watch the trace."
        }
        video.seek(toFrame: result.impactFrame)
        showDrawer = false
    }

    private func recomputeStats() {
        let (stats, warnings) = TrajectoryFit.computeStats(marks: marks, fps: video.fps)
        marks.stats = stats
        marks.warnings = warnings
    }

    private func clearMarks() {
        marks.reset()
        mode = .idle
        statusText = "Marks and track cleared."
    }

    // MARK: - Stat editing

    private func beginEdit(_ key: StatKey) {
        editValueText = marks.displayValue(for: key).map { String(format: "%.\(key.decimals)f", $0) } ?? ""
        editingStat = key
    }

    private func commitEdit() {
        guard let key = editingStat else { return }
        if let v = Double(editValueText) {
            marks.overrides[key] = v
            statusText = "\(key.label.capitalized) overridden to \(editValueText) \(key.unit)."
        }
        editingStat = nil
    }
}

#Preview {
    ContentView()
}
