import SwiftUI
import PhotosUI

/// Bottom-sheet control drawer — the mobile reinterpretation of the desktop
/// app's left sidebar. Same five workflow sections, laid out for thumb reach
/// instead of a mouse.
struct ControlsDrawer: View {
    @ObservedObject var video: VideoController
    @ObservedObject var marks: ShotMarks

    @Binding var mode: MarkMode
    @Binding var showRing: Bool
    @Binding var visibleTiles: Set<StatKey>
    @Binding var calibrationDistanceText: String
    @Binding var calibrationUnit: DistanceUnit
    @Binding var photoItem: PhotosPickerItem?

    var onTrack: () -> Void
    var onClear: () -> Void
    var onEditStat: (StatKey) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                section("1 · VIDEO") {
                    PhotosPicker(selection: $photoItem, matching: .videos) {
                        Label("Choose Video", systemImage: "square.and.arrow.up")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.primaryTM)

                    if video.isLoaded {
                        Text("\(Int(video.naturalSize.width))×\(Int(video.naturalSize.height))  ·  \(video.fps, specifier: "%.1f") fps  ·  \(video.frameCount) frames")
                            .font(.caption).foregroundColor(Theme.textMuted)
                    }

                    HStack {
                        Button { video.rotateCCW() } label: { Image(systemName: "rotate.left") }
                            .buttonStyle(.widget)
                        Text("\(video.rotationDegrees)°").font(.subheadline.bold()).foregroundColor(Theme.orange)
                            .frame(width: 50)
                        Button { video.rotateCW() } label: { Image(systemName: "rotate.right") }
                            .buttonStyle(.widget)
                    }
                }

                section("2 · CALIBRATION") {
                    Button {
                        mode = (mode == .calibrate) ? .idle : .calibrate
                    } label: {
                        Label("Draw Calibration Line", systemImage: "ruler")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.widget(active: mode == .calibrate))

                    HStack {
                        TextField("Known distance", text: $calibrationDistanceText)
                            .keyboardType(.decimalPad)
                            .textFieldStyle(.roundedBorder)
                        Picker("", selection: $calibrationUnit) {
                            ForEach(DistanceUnit.allCases) { u in Text(u.rawValue.capitalized).tag(u) }
                        }
                        .pickerStyle(.menu)
                    }

                    if let ypp = marks.yardsPerPixel {
                        Text(String(format: "Calibrated: 1px = %.4f yd", ypp))
                            .font(.caption).foregroundColor(Theme.textMuted)
                    } else {
                        Text("Not calibrated — stats will show '--'")
                            .font(.caption).foregroundColor(Theme.textMuted)
                    }
                }

                section("3 · MARK THE SHOT") {
                    modeButton("Click Ball — Launch Frames", icon: "plus.circle", target: .launch)
                    Text("Launch clicks: \(marks.launchClicks.count)   (minimum 3)")
                        .font(.caption).foregroundColor(Theme.textMuted)

                    modeButton("Mark Apex", icon: "arrow.up.to.line", target: .apex)
                    Text(marks.apexClick.map { "Apex: frame \($0.frame)" } ?? "Apex: not set")
                        .font(.caption).foregroundColor(Theme.textMuted)

                    modeButton("Mark Landing Point", icon: "arrow.down.to.line", target: .landing)
                    Text(marks.landingClick.map { "Landing: frame \($0.frame)" } ?? "Landing: not set")
                        .font(.caption).foregroundColor(Theme.textMuted)
                }

                section("4 · TRACK") {
                    Button(action: onTrack) {
                        Label("Track Shot", systemImage: "location.viewfinder").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.primaryTM)

                    Button(role: .destructive, action: onClear) {
                        Label("Clear Marks & Track", systemImage: "xmark.circle").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.widget)
                }

                section("5 · DATA LAYOUT") {
                    Toggle("Tracking ring", isOn: $showRing).tint(Theme.orange)
                    ForEach(StatKey.allCases) { key in
                        Toggle("Tile — \(key.label.capitalized)", isOn: Binding(
                            get: { visibleTiles.contains(key) },
                            set: { on in if on { visibleTiles.insert(key) } else { visibleTiles.remove(key) } }
                        )).tint(Theme.orange)
                    }
                }

                section("SHOT DATA") {
                    Text("Tap a tile on the video (once tracked) to override its value.")
                        .font(.caption2).foregroundColor(Theme.textMuted)
                    ForEach(StatKey.allCases) { key in
                        StatRow(key: key, marks: marks) { onEditStat(key) }
                    }
                }
            }
            .padding(16)
        }
        .background(Theme.bgPanel)
    }

    @ViewBuilder
    private func modeButton(_ title: String, icon: String, target: MarkMode) -> some View {
        Button {
            mode = (mode == target) ? .idle : target
        } label: {
            Label(title, systemImage: icon).frame(maxWidth: .infinity)
        }
        .buttonStyle(.widget(active: mode == target))
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title).font(.caption.bold()).foregroundColor(Theme.orange)
                Rectangle().fill(Theme.border).frame(height: 1)
            }
            content()
        }
    }
}

private struct StatRow: View {
    let key: StatKey
    @ObservedObject var marks: ShotMarks
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack {
                Text(key.label).font(.caption.bold()).foregroundColor(Theme.orange)
                Spacer()
                let val = marks.displayValue(for: key)
                Text(val == nil ? "-- \(key.unit)" : String(format: "%.\(key.decimals)f %@", val!, key.unit))
                    .font(.subheadline.bold())
                    .foregroundColor(marks.isWarning(key) ? Theme.orange : Theme.textPrimary)
                if marks.overrides[key] != nil {
                    Image(systemName: "pencil").font(.caption2).foregroundColor(Theme.textMuted)
                } else if marks.isWarning(key) {
                    Image(systemName: "exclamationmark.triangle.fill").font(.caption2).foregroundColor(Theme.warn)
                }
            }
            .padding(10)
            .background(Theme.bgPanel2)
            .cornerRadius(8)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Button styles

struct PrimaryTMButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.bold())
            .padding(.vertical, 11)
            .background(Theme.orange.opacity(configuration.isPressed ? 0.8 : 1))
            .foregroundColor(.black)
            .cornerRadius(9)
    }
}

struct WidgetButtonStyle: ButtonStyle {
    var active: Bool = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.bold())
            .padding(.vertical, 9)
            .padding(.horizontal, 10)
            .background(active ? Theme.orange : Theme.bgWidget)
            .foregroundColor(active ? .black : Theme.textPrimary)
            .cornerRadius(8)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border, lineWidth: active ? 0 : 1))
    }
}

extension ButtonStyle where Self == PrimaryTMButtonStyle {
    static var primaryTM: PrimaryTMButtonStyle { PrimaryTMButtonStyle() }
}
extension ButtonStyle where Self == WidgetButtonStyle {
    static var widget: WidgetButtonStyle { WidgetButtonStyle() }
    static func widget(active: Bool) -> WidgetButtonStyle { WidgetButtonStyle(active: active) }
}
