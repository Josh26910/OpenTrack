import Foundation
import AVFoundation
import CoreGraphics
import Combine

/// Wraps AVPlayer with the frame-accurate transport the editor needs:
/// exact frame stepping, a stable fps, and a published current frame index
/// that both the transport bar and the marking UI can read.
@MainActor
final class VideoController: ObservableObject {
    @Published var player = AVPlayer()
    @Published var isLoaded = false
    @Published var isPlaying = false
    @Published var currentFrame = 0
    @Published var frameCount = 1
    @Published var fps: Double = 30
    @Published var naturalSize: CGSize = .zero
    @Published var rotationDegrees: Int = 0   // 0/90/180/270 clockwise, display-only
    @Published var videoURL: URL?

    private var timeObserver: Any?

    func load(url: URL) async {
        pause()
        let asset = AVURLAsset(url: url)
        guard let track = try? await asset.loadTracks(withMediaType: .video).first else { return }

        let nominalFPS = try? await track.load(.nominalFrameRate)
        let duration = try? await asset.load(.duration)
        let size = try? await track.load(.naturalSize)

        let item = AVPlayerItem(asset: asset)
        removeTimeObserver()
        player.replaceCurrentItem(with: item)

        self.fps = Double(nominalFPS ?? 30) > 1 ? Double(nominalFPS ?? 30) : 30
        self.naturalSize = size ?? CGSize(width: 1920, height: 1080)
        let secs = (duration ?? .zero).seconds
        self.frameCount = max(1, Int((secs * fps).rounded()))
        self.rotationDegrees = 0
        self.videoURL = url
        self.currentFrame = 0
        self.isLoaded = true

        addTimeObserver()
    }

    private func addTimeObserver() {
        let interval = CMTime(value: 1, timescale: Int32(max(1, fps.rounded())))
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] time in
            guard let self else { return }
            self.currentFrame = Self.frameIndex(for: time, fps: self.fps)
        }
    }

    private func removeTimeObserver() {
        if let obs = timeObserver { player.removeTimeObserver(obs) }
        timeObserver = nil
    }

    static func frameIndex(for time: CMTime, fps: Double) -> Int {
        max(0, Int((time.seconds * fps).rounded()))
    }

    func time(forFrame frame: Int) -> CMTime {
        CMTime(seconds: Double(frame) / fps, preferredTimescale: 600)
    }

    func seek(toFrame frame: Int) {
        let clamped = max(0, min(frame, frameCount - 1))
        currentFrame = clamped
        player.seek(to: time(forFrame: clamped), toleranceBefore: .zero, toleranceAfter: .zero)
    }

    func step(_ delta: Int) {
        pause()
        seek(toFrame: currentFrame + delta)
    }

    func togglePlay() {
        if isPlaying { pause() } else { play() }
    }

    func play() {
        guard isLoaded else { return }
        if currentFrame >= frameCount - 1 { seek(toFrame: 0) }
        player.rate = 1.0
        player.play()
        isPlaying = true
    }

    func pause() {
        player.pause()
        isPlaying = false
    }

    func rotateCW() { rotationDegrees = (rotationDegrees + 90) % 360 }
    func rotateCCW() { rotationDegrees = (rotationDegrees + 270) % 360 }

    /// Size of the frame as actually displayed, after rotation swaps w/h.
    var displaySize: CGSize {
        rotationDegrees == 90 || rotationDegrees == 270
            ? CGSize(width: naturalSize.height, height: naturalSize.width)
            : naturalSize
    }

    // MARK: - Coordinate mapping (rotated/displayed <-> original video space)

    func rotatedToVideo(_ p: CGPoint) -> CGPoint {
        let w = naturalSize.width, h = naturalSize.height
        switch rotationDegrees {
        case 90: return CGPoint(x: p.y, y: h - 1 - p.x)
        case 180: return CGPoint(x: w - 1 - p.x, y: h - 1 - p.y)
        case 270: return CGPoint(x: w - 1 - p.y, y: p.x)
        default: return p
        }
    }

    func videoToRotated(_ p: CGPoint) -> CGPoint {
        let w = naturalSize.width, h = naturalSize.height
        switch rotationDegrees {
        case 90: return CGPoint(x: h - 1 - p.y, y: p.x)
        case 180: return CGPoint(x: w - 1 - p.x, y: h - 1 - p.y)
        case 270: return CGPoint(x: p.y, y: w - 1 - p.x)
        default: return p
        }
    }
}
