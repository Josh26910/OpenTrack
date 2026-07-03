import Foundation

/// Which stat tile, matching the desktop editor's STAT_DEFS.
enum StatKey: String, CaseIterable, Identifiable {
    case ballSpeed = "ball_speed"
    case carry
    case launch
    case height

    var id: String { rawValue }

    var label: String {
        switch self {
        case .ballSpeed: return "BALL SPEED"
        case .carry: return "CARRY"
        case .launch: return "LAUNCH ANGLE"
        case .height: return "HEIGHT (APEX)"
        }
    }

    var unit: String {
        switch self {
        case .ballSpeed: return "mph"
        case .carry: return "yds"
        case .launch: return "deg"
        case .height: return "ft"
        }
    }

    var decimals: Int {
        switch self {
        case .height: return 0
        default: return 1
        }
    }

    /// Generous plausibility bounds — a value outside these almost always
    /// means a bad calibration or a mis-click, not a real shot.
    var bounds: ClosedRange<Double> {
        switch self {
        case .ballSpeed: return 1.0...230.0
        case .carry: return 1.0...420.0
        case .launch: return -15.0...60.0
        case .height: return 1.0...220.0
        }
    }
}

enum DistanceUnit: String, CaseIterable, Identifiable {
    case yards, feet, meters, inches
    var id: String { rawValue }
    var toYards: Double {
        switch self {
        case .yards: return 1.0
        case .feet: return 1.0 / 3.0
        case .meters: return 1.09361
        case .inches: return 1.0 / 36.0
        }
    }
}

enum Physics {
    static let ypsToMph = 3600.0 / 1760.0
    static let yardsToFeet = 3.0
}
