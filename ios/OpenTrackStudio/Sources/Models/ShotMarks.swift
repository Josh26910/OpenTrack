import Foundation
import CoreGraphics

/// A single manual click: which frame it was recorded on, and where in the
/// ORIGINAL (unrotated) video's pixel space.
struct FrameClick: Equatable {
    var frame: Int
    var point: CGPoint
}

enum MarkMode: String {
    case idle, launch, apex, landing, calibrate
}

/// All the user-entered marks for the shot being annotated — mirrors the
/// desktop app's launch_clicks / apex_click / landing_click / calibration.
final class ShotMarks: ObservableObject {
    @Published var launchClicks: [FrameClick] = []
    @Published var apexClick: FrameClick?
    @Published var landingClick: FrameClick?

    @Published var calibrationLine: (CGPoint, CGPoint)?
    @Published var yardsPerPixel: Double?

    @Published var trajectory: [Int: CGPoint] = [:]
    @Published var impactFrame: Int?
    @Published var apexFrame: Int?
    @Published var landingFrame: Int?

    @Published var stats: [StatKey: Double] = [:]
    @Published var overrides: [StatKey: Double] = [:]
    @Published var warnings: Set<StatKey> = []

    var fitX: QuadCoeffs?
    var fitY: QuadCoeffs?

    func reset() {
        launchClicks = []
        apexClick = nil
        landingClick = nil
        trajectory = [:]
        impactFrame = nil
        apexFrame = nil
        landingFrame = nil
        stats = [:]
        overrides = [:]
        warnings = []
        fitX = nil
        fitY = nil
    }

    func resetCalibration() {
        calibrationLine = nil
        yardsPerPixel = nil
    }

    func displayValue(for key: StatKey) -> Double? {
        overrides[key] ?? stats[key]
    }

    func isWarning(_ key: StatKey) -> Bool {
        overrides[key] == nil && warnings.contains(key)
    }

    var canTrack: Bool {
        launchClicks.count >= 3 && apexClick != nil && landingClick != nil
    }

    /// Fast, cheap piecewise-linear path so the ring follows the ball live
    /// while marking, before "Track Shot" computes the real physics fit.
    func updateLivePreviewTrajectory() {
        var points = launchClicks
        if let a = apexClick { points.append(a) }
        if let l = landingClick { points.append(l) }
        guard points.count >= 2 else { trajectory = [:]; return }

        var seen = Set<Int>()
        var uniq: [FrameClick] = []
        for p in points.sorted(by: { $0.frame < $1.frame }) where !seen.contains(p.frame) {
            uniq.append(p); seen.insert(p.frame)
        }
        guard uniq.count >= 2 else { trajectory = [:]; return }

        var traj: [Int: CGPoint] = [:]
        for (a, b) in zip(uniq, uniq.dropFirst()) {
            let gap = b.frame - a.frame
            guard gap > 0 else { continue }
            for f in a.frame...b.frame {
                let t = Double(f - a.frame) / Double(gap)
                let x = a.point.x + (b.point.x - a.point.x) * t
                let y = a.point.y + (b.point.y - a.point.y) * t
                traj[f] = CGPoint(x: x, y: y)
            }
        }
        trajectory = traj
    }
}

struct QuadCoeffs { var a: Double; var b: Double; var c: Double
    func eval(_ t: Double) -> Double { a * t * t + b * t + c }
}
