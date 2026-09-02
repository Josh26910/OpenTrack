import SwiftUI

/// TrackMan-inspired dark palette, shared across the app.
enum Theme {
    static let orange       = Color(hex: 0xFF5A00)
    static let orangeDark   = Color(hex: 0xC24500)
    static let orangeBright = Color(hex: 0xFF8A3D)

    static let bgRoot    = Color(hex: 0x0A0B0E)
    static let bgPanel   = Color(hex: 0x15171C)
    static let bgPanel2  = Color(hex: 0x1B1E25)
    static let bgWidget  = Color(hex: 0x21242B)

    static let textPrimary = Color(hex: 0xE7EAF0)
    static let textMuted   = Color(hex: 0x9AA3B2)
    static let textMuted2  = Color(hex: 0x5F6772)

    static let border  = Color(hex: 0x262A32)
    static let warn    = Color(hex: 0x00C8FF)
    static let green   = Color(hex: 0x00E676)

    static let cardGradient = LinearGradient(
        colors: [Color(hex: 0x171A20), Color(hex: 0x121419)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )

    static let backdropGradient = RadialGradient(
        colors: [orange.opacity(0.10), .clear],
        center: UnitPoint(x: 0.75, y: -0.05), startRadius: 4, endRadius: 520
    )
}

extension Color {
    init(hex: UInt32, alpha: Double = 1.0) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255.0,
            green: Double((hex >> 8) & 0xFF) / 255.0,
            blue: Double(hex & 0xFF) / 255.0,
            opacity: alpha
        )
    }
}
