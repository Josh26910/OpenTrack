import Foundation
import CoreGraphics

/// Port of the desktop editor's physics-assisted projectile fit
/// (`_fit_trajectory` / `_compute_stats` in launch_monitor_editor_10_5.py).
///
/// Both x(t) and y(t) are modelled as quadratics in time -- the shape of
/// constant-acceleration projectile motion. A weighted least-squares fit
/// is used for the overall stat computation (launch angle), while the
/// on-screen path is built segment-by-segment so it always passes exactly
/// through every clicked frame and only "invents" motion across the gaps
/// the user didn't click (last-launch -> apex, apex -> landing).
enum TrajectoryFit {

    struct Result {
        var trajectory: [Int: CGPoint]
        var fitX: QuadCoeffs
        var fitY: QuadCoeffs
        var impactFrame: Int
        var apexFrame: Int
        var landingFrame: Int
    }

    static func fit(launchClicks: [FrameClick], apex: FrameClick, landing: FrameClick, fps: Double) -> Result {
        let f0 = launchClicks[0].frame
        var pts = launchClicks
        pts.append(apex)
        pts.append(landing)

        let ts = pts.map { Double($0.frame - f0) / fps }
        let xs = pts.map { Double($0.point.x) }
        let ys = pts.map { Double($0.point.y) }

        var weights = [Double](repeating: 1.0, count: pts.count)
        weights[0] = 5.0
        let nLaunch = launchClicks.count
        weights[nLaunch] = 8.0
        weights[nLaunch + 1] = 8.0

        let fitX = weightedQuadFit(t: ts, y: xs, weights: weights)
        let fitY = weightedQuadFit(t: ts, y: ys, weights: weights)

        let traj = buildSegmentedTrajectory(pts: pts, nLaunch: nLaunch)

        return Result(
            trajectory: traj, fitX: fitX, fitY: fitY,
            impactFrame: f0, apexFrame: apex.frame, landingFrame: landing.frame
        )
    }

    /// Weighted least-squares quadratic fit: y = a*t^2 + b*t + c.
    /// Closed-form via the normal equations (3x3 solve) -- the model is
    /// linear in its coefficients, so this is exact, no iteration needed.
    static func weightedQuadFit(t: [Double], y: [Double], weights: [Double]) -> QuadCoeffs {
        var s = [[Double]](repeating: [Double](repeating: 0, count: 4), count: 3)
        for i in 0..<t.count {
            let w = weights[i], ti = t[i], yi = y[i]
            let t2 = ti * ti, t3 = t2 * ti, t4 = t2 * t2
            s[0][0] += w * t4; s[0][1] += w * t3; s[0][2] += w * t2; s[0][3] += w * t2 * yi
            s[1][0] += w * t3; s[1][1] += w * t2; s[1][2] += w * ti; s[1][3] += w * ti * yi
            s[2][0] += w * t2; s[2][1] += w * ti; s[2][2] += w;      s[2][3] += w * yi
        }
        let sol = solve3x3(s)
        return QuadCoeffs(a: sol[0], b: sol[1], c: sol[2])
    }

    private static func solve3x3(_ m: [[Double]]) -> [Double] {
        var a = m
        for col in 0..<3 {
            var pivot = col
            for row in (col + 1)..<3 where abs(a[row][col]) > abs(a[pivot][col]) { pivot = row }
            a.swapAt(col, pivot)
            let pv = a[col][col]
            guard abs(pv) > 1e-12 else { continue }
            for row in 0..<3 where row != col {
                let factor = a[row][col] / pv
                for k in col...3 { a[row][k] -= factor * a[col][k] }
            }
        }
        return (0..<3).map { i in abs(a[i][i]) > 1e-12 ? a[i][3] / a[i][i] : 0 }
    }

    // MARK: - Segmented display path

    private static let gapThreshold = 5
    private static let v0TrailPoints = 4
    private static let v0TrailSpan = 12

    /// Launch speed for a constant-acceleration axis that must travel D over
    /// T frames without overshooting: point toward D, clamp to at most full
    /// deceleration-to-rest (2D/T).
    private static func monotoneV0(_ v: Double, _ d: Double, _ t: Double) -> Double {
        let lo = min(0.0, 2.0 * d / t), hi = max(0.0, 2.0 * d / t)
        return min(max(v, lo), hi)
    }

    /// How much of a T-frame gap can be spent at the constant clicked speed
    /// v0 before a deceleration-to-zero phase must start, landing exactly on
    /// distance D at zero velocity. Returns (holdFrames, easePower, tooSlow).
    private static func holdThenEase(_ v0: Double, _ d: Double, _ t: Double) -> (Double, Double?, Bool) {
        let r = abs(d) > 1e-6 ? (v0 * t / d) : 2.0
        if r <= 1.0 { return (0, nil, true) }
        if r <= 2.0 { return (t * (2.0 - r) / r, nil, false) }
        return (0, r - 1.0, false)
    }

    private static func linearRegressionSlope(_ pts: [(Double, Double)]) -> Double {
        let n = Double(pts.count)
        let sx = pts.reduce(0) { $0 + $1.0 }, sy = pts.reduce(0) { $0 + $1.1 }
        let sxx = pts.reduce(0) { $0 + $1.0 * $1.0 }, sxy = pts.reduce(0) { $0 + $1.0 * $1.1 }
        let denom = n * sxx - sx * sx
        guard abs(denom) > 1e-9 else { return 0 }
        return (n * sxy - sx * sy) / denom
    }

    private static func buildSegmentedTrajectory(pts: [FrameClick], nLaunch: Int) -> [Int: CGPoint] {
        var traj: [Int: CGPoint] = [:]
        var prevEndVel: (Double, Double)?
        var prevWasCurve = false

        for i in 0..<(pts.count - 1) {
            let a = pts[i], b = pts[i + 1]
            traj[a.frame] = a.point
            let gap = b.frame - a.frame
            if gap < gapThreshold {
                if gap >= 1 {
                    for f in (a.frame + 1)..<b.frame {
                        let frac = Double(f - a.frame) / Double(gap)
                        let x = a.point.x + (b.point.x - a.point.x) * frac
                        let y = a.point.y + (b.point.y - a.point.y) * frac
                        traj[f] = CGPoint(x: x, y: y)
                    }
                    prevEndVel = (Double(b.point.x - a.point.x) / Double(gap),
                                  Double(b.point.y - a.point.y) / Double(gap))
                    prevWasCurve = false
                }
                continue
            }

            let T = Double(gap)
            let Dx = Double(b.point.x - a.point.x), Dy = Double(b.point.y - a.point.y)

            let vIn: (Double, Double)
            if prevWasCurve, let pv = prevEndVel {
                vIn = pv
            } else {
                let trail = pts[0...i].filter { a.frame - $0.frame <= v0TrailSpan }.suffix(v0TrailPoints)
                if trail.count >= 2 {
                    let txs = trail.map { (Double($0.frame), Double($0.point.x)) }
                    let tys = trail.map { (Double($0.frame), Double($0.point.y)) }
                    vIn = (linearRegressionSlope(txs), linearRegressionSlope(tys))
                } else if let pv = prevEndVel {
                    vIn = pv
                } else {
                    vIn = (Dx / T, Dy / T)
                }
            }

            let v0x = monotoneV0(vIn.0, Dx, T)
            let sax = 2.0 * (Dx - v0x * T) / (T * T)

            let endsAtApex = (i + 1 == nLaunch)
            let startsAtApex = (i == nLaunch)

            var holdH: Double?
            var easeP: Double?
            var m0y = 0.0
            var v0y = 0.0, say = 0.0
            var vyEnd = 0.0

            if startsAtApex {
                vyEnd = 2.0 * Dy / T
            } else if endsAtApex {
                let (h, ep, tooSlow) = holdThenEase(vIn.1, Dy, T)
                if tooSlow {
                    let lo = min(0.0, 3.0 * Dy / T), hi = max(0.0, 3.0 * Dy / T)
                    m0y = min(max(vIn.1, lo), hi)
                } else if ep == nil {
                    holdH = h
                } else {
                    easeP = ep
                }
                vyEnd = 0.0
            } else {
                v0y = monotoneV0(vIn.1, Dy, T)
                say = 2.0 * (Dy - v0y * T) / (T * T)
                vyEnd = v0y + say * T
            }

            if gap > 1 {
                for f in (a.frame + 1)..<b.frame {
                    let tau = Double(f - a.frame)
                    let x = a.point.x + v0x * tau + 0.5 * sax * tau * tau
                    var y: Double
                    if endsAtApex, let ep = easeP {
                        let frac = 1.0 - pow(1.0 - tau / T, ep + 1.0)
                        y = Double(a.point.y) + Dy * frac
                    } else if endsAtApex, let h = holdH {
                        if tau <= h {
                            y = Double(a.point.y) + vIn.1 * tau
                        } else {
                            let eTau = tau - h, E = T - h
                            let sy = Double(a.point.y) + vIn.1 * h
                            y = sy + vIn.1 * eTau - 0.5 * (vIn.1 / E) * eTau * eTau
                        }
                    } else if endsAtApex {
                        let s = tau / T
                        let h00 = (2.0 * s - 3.0) * s * s + 1.0
                        let h10 = ((s - 2.0) * s + 1.0) * s
                        y = h00 * Double(a.point.y) + (1.0 - h00) * Double(b.point.y) + h10 * T * m0y
                    } else if startsAtApex {
                        y = Double(a.point.y) + Dy * pow(tau / T, 2)
                    } else {
                        y = Double(a.point.y) + v0y * tau + 0.5 * say * tau * tau
                    }
                    traj[f] = CGPoint(x: x, y: y)
                }
            }
            prevEndVel = (v0x + sax * T, vyEnd)
            prevWasCurve = true
        }
        if let last = pts.last { traj[last.frame] = last.point }
        return traj
    }

    // MARK: - Stats

    static func computeStats(marks: ShotMarks, fps: Double) -> ([StatKey: Double], Set<StatKey>) {
        var stats: [StatKey: Double] = [:]
        let scale = marks.yardsPerPixel

        var pxSpeeds: [Double] = []
        for (a, b) in zip(marks.launchClicks, marks.launchClicks.dropFirst()) {
            let df = b.frame - a.frame
            guard df > 0 else { continue }
            let dist = hypot(Double(b.point.x - a.point.x), Double(b.point.y - a.point.y))
            pxSpeeds.append(dist * fps / Double(df))
        }
        let pxPerS = pxSpeeds.isEmpty ? 0 : pxSpeeds.reduce(0, +) / Double(pxSpeeds.count)
        if let scale, pxPerS > 0 {
            stats[.ballSpeed] = pxPerS * scale * Physics.ypsToMph
        }

        if let fx = marks.fitX, let fy = marks.fitY {
            let vx0 = fx.b, vy0 = -fy.b
            if abs(vx0) > 1e-6 || abs(vy0) > 1e-6 {
                stats[.launch] = atan2(vy0, abs(vx0)) * 180.0 / .pi
            }
        }

        if let scale, let first = marks.launchClicks.first, let landing = marks.landingClick {
            stats[.carry] = hypot(Double(landing.point.x - first.point.x),
                                   Double(landing.point.y - first.point.y)) * scale
        }

        if let scale, let fy = marks.fitY, let first = marks.launchClicks.first, let apex = marks.apexClick {
            let yApex: Double
            if abs(fy.a) > 1e-9 {
                let tApex = -fy.b / (2.0 * fy.a)
                yApex = fy.eval(tApex)
            } else {
                yApex = Double(apex.point.y)
            }
            let hPx = max(0.0, Double(first.point.y) - yApex)
            stats[.height] = hPx * scale * Physics.yardsToFeet
        }

        var warnings = Set<StatKey>()
        for (key, val) in stats where !key.bounds.contains(val) {
            warnings.insert(key)
        }
        return (stats, warnings)
    }
}
