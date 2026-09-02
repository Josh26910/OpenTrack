import colors from "@/constants/colors";

/**
 * OpenTrack Mobile is always-dark (matches the desktop/iOS/web clients'
 * TrackMan-inspired look), so this ignores the device color scheme and
 * always returns the dark palette plus the shared `radius` token.
 */
export function useColors() {
  return { ...colors.dark, radius: colors.radius };
}
