import SwiftUI

/// Draws every overlay on top of the (already-rotated, already-scaled)
/// player layer: calibration line, click markers, the tracking ring, and
/// the fading stat tiles. Coordinates in are all in ROTATED VIDEO PIXEL
/// space; `scale` converts to this view's own point space.
struct VideoOverlayView: View {
    @ObservedObject var video: VideoController
    @ObservedObject var marks: ShotMarks
    var mode: MarkMode
    var scale: CGFloat
    var showRing: Bool
    var visibleTiles: Set<StatKey>
    var calStart: CGPoint?
    var calCurrent: CGPoint?
    @Binding var tileRects: [StatKey: CGRect]

    var body: some View {
        Canvas { context, size in
            drawCalibration(&context, size: size)
            drawClickMarkers(&context, size: size)
            if !marks.trajectory.isEmpty {
                if showRing { drawRing(&context, size: size) }
                drawStatTiles(&context, size: size)
            }
        }
        .allowsHitTesting(false)
    }

    private func toView(_ p: CGPoint) -> CGPoint {
        CGPoint(x: p.x * scale, y: p.y * scale)
    }

    private func rotated(_ click: FrameClick) -> CGPoint {
        toView(video.videoToRotated(click.point))
    }

    // MARK: - Calibration

    private func drawCalibration(_ context: inout GraphicsContext, size: CGSize) {
        guard mode == .calibrate else { return }
        if let s = calStart, let c = calCurrent {
            let p1 = toView(s), p2 = toView(c)
            var path = Path()
            path.move(to: p1); path.addLine(to: p2)
            context.stroke(path, with: .color(.black.opacity(0.8)), lineWidth: 5)
            context.stroke(path, with: .color(Theme.orange), lineWidth: 2)
            for p in [p1, p2] {
                context.fill(Path(ellipseIn: CGRect(x: p.x - 6, y: p.y - 6, width: 12, height: 12)),
                             with: .color(Theme.orange))
            }
            let lengthPx = hypot(c.x - s.x, c.y - s.y)
            let mid = CGPoint(x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 - 14)
            context.draw(Text("\(Int(lengthPx))px").font(.caption).foregroundColor(.white), at: mid)
        } else if let line = marks.calibrationLine {
            let p1 = toView(line.0), p2 = toView(line.1)
            var path = Path()
            path.move(to: p1); path.addLine(to: p2)
            context.stroke(path, with: .color(Theme.orange.opacity(0.6)), lineWidth: 1)
        }
    }

    // MARK: - Click markers

    private func drawClickMarkers(_ context: inout GraphicsContext, size: CGSize) {
        let rDot: CGFloat = max(6, video.naturalSize.width / 140) * scale
        let rHalo = rDot + 3
        let rPip = max(2, rDot / 3)

        func mark(_ p: CGPoint, _ label: String, onFrame: Bool) {
            if onFrame {
                context.stroke(Path(ellipseIn: CGRect(x: p.x - rHalo, y: p.y - rHalo, width: rHalo * 2, height: rHalo * 2)),
                                with: .color(.black), lineWidth: rHalo / 2)
                context.fill(Path(ellipseIn: CGRect(x: p.x - rDot, y: p.y - rDot, width: rDot * 2, height: rDot * 2)),
                             with: .color(Theme.orange))
                context.stroke(Path(ellipseIn: CGRect(x: p.x - rDot, y: p.y - rDot, width: rDot * 2, height: rDot * 2)),
                               with: .color(.white), lineWidth: 1)
                context.draw(Text(label).font(.caption).bold().foregroundColor(Theme.orange),
                             at: CGPoint(x: p.x + rDot + 14, y: p.y))
            } else {
                context.fill(Path(ellipseIn: CGRect(x: p.x - rPip, y: p.y - rPip, width: rPip * 2, height: rPip * 2)),
                             with: .color(Color(hex: 0x5A6E82)))
            }
        }

        for (i, click) in marks.launchClicks.enumerated() {
            mark(rotated(click), "\(i + 1)", onFrame: click.frame == video.currentFrame)
        }
        if let apex = marks.apexClick {
            mark(rotated(apex), "APEX", onFrame: apex.frame == video.currentFrame)
        }
        if let landing = marks.landingClick {
            mark(rotated(landing), "LAND", onFrame: landing.frame == video.currentFrame)
        }
    }

    // MARK: - Tracking ring

    private func drawRing(_ context: inout GraphicsContext, size: CGSize) {
        guard let vp = marks.trajectory[video.currentFrame] else { return }
        let p = toView(video.videoToRotated(vp))
        let r = max(9, video.displaySize.width * scale / 90.0)
        guard p.x + r >= 0, p.x - r < size.width, p.y + r >= 0, p.y - r < size.height else { return }

        let ringRect = CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)
        context.stroke(Path(ellipseIn: ringRect), with: .color(.black), lineWidth: 5)
        context.stroke(Path(ellipseIn: ringRect), with: .color(Theme.orange), lineWidth: 3)
        context.fill(Path(ellipseIn: CGRect(x: p.x - 2, y: p.y - 2, width: 4, height: 4)), with: .color(.white))
    }

    // MARK: - Stat tiles

    private func drawStatTiles(_ context: inout GraphicsContext, size: CGSize) {
        guard let apexFrame = marks.apexFrame, video.currentFrame >= apexFrame else {
            if !tileRects.isEmpty { DispatchQueue.main.async { tileRects = [:] } }
            return
        }
        let visible = StatKey.allCases.filter { visibleTiles.contains($0) }
        guard !visible.isEmpty else { return }

        let w = size.width
        let gap = max(6, w * 0.02)
        let n = CGFloat(visible.count)
        var tileW = min(w * 0.26, (w - (n + 1) * gap) / max(n, 1))
        tileW = max(80, tileW)
        let tileH = tileW * 0.52
        let totalW = n * tileW + (n - 1) * gap
        let x0 = (w - totalW) / 2
        let y0 = max(8, size.height * 0.04)

        let fade = min(1.0, Double(video.currentFrame - apexFrame + 1) / 10.0)
        let alpha = 0.78 * fade

        var rects: [StatKey: CGRect] = [:]
        for (i, key) in visible.enumerated() {
            let x1 = x0 + CGFloat(i) * (tileW + gap)
            let rect = CGRect(x: x1, y: y0, width: tileW, height: tileH)
            rects[key] = rect

            context.fill(Path(roundedRect: rect, cornerRadius: 6), with: .color(.black.opacity(alpha)))
            let accent = CGRect(x: rect.minX, y: rect.minY, width: max(3, tileW / 40), height: tileH)
            context.fill(Path(accent), with: .color(Theme.orange.opacity(fade)))
            context.stroke(Path(roundedRect: rect, cornerRadius: 6), with: .color(.white.opacity(0.08)), lineWidth: 1)

            let cx = rect.midX
            context.draw(Text(key.label).font(.system(size: 9, weight: .bold)).foregroundColor(Theme.orange.opacity(fade)),
                         at: CGPoint(x: cx, y: rect.minY + tileH * 0.20))

            let val = marks.displayValue(for: key)
            let vtext = val == nil ? "--" : String(format: "%.\(key.decimals)f", val!)
            context.draw(Text(vtext).font(.system(size: tileW * 0.19, weight: .bold)).foregroundColor(.white.opacity(fade)),
                         at: CGPoint(x: cx, y: rect.minY + tileH * 0.52))

            context.draw(Text(key.unit).font(.system(size: 8)).foregroundColor(Color(hex: 0x9A9AA0).opacity(fade)),
                         at: CGPoint(x: cx, y: rect.minY + tileH * 0.82))

            if marks.isWarning(key) {
                let warnR = max(6, tileH * 0.11)
                let warnC = CGPoint(x: rect.maxX - warnR - 4, y: rect.minY + warnR + 4)
                context.fill(Path(ellipseIn: CGRect(x: warnC.x - warnR, y: warnC.y - warnR, width: warnR * 2, height: warnR * 2)),
                             with: .color(Theme.warn.opacity(fade)))
                context.draw(Text("!").font(.system(size: warnR)).bold().foregroundColor(.black), at: warnC)
            }
        }
        DispatchQueue.main.async { tileRects = rects }
    }
}
