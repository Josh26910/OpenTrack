import SwiftUI

struct TransportBar: View {
    @ObservedObject var video: VideoController
    var statusText: String

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 14) {
                transportButton("backward.frame.fill") { video.step(-1) }
                Button {
                    video.togglePlay()
                } label: {
                    Image(systemName: video.isPlaying ? "pause.fill" : "play.fill")
                        .font(.title3.bold())
                        .frame(width: 52, height: 40)
                        .background(Theme.orange)
                        .foregroundColor(.black)
                        .cornerRadius(9)
                }
                transportButton("forward.frame.fill") { video.step(1) }

                Text("frame \(video.currentFrame) / \(max(0, video.frameCount - 1))")
                    .font(.caption.monospacedDigit())
                    .foregroundColor(Theme.textMuted)
                    .frame(width: 130, alignment: .leading)

                Slider(
                    value: Binding(
                        get: { Double(video.currentFrame) },
                        set: { video.seek(toFrame: Int($0.rounded())) }
                    ),
                    in: 0...Double(max(1, video.frameCount - 1))
                )
                .tint(Theme.orange)
                .disabled(!video.isLoaded)
            }
            Text(statusText)
                .font(.caption2)
                .foregroundColor(Theme.textMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Theme.bgPanel)
    }

    private func transportButton(_ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.subheadline.bold())
                .frame(width: 40, height: 40)
                .background(Theme.bgWidget)
                .foregroundColor(Theme.textPrimary)
                .cornerRadius(8)
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border, lineWidth: 1))
        }
    }
}
