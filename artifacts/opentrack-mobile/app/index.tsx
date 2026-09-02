import { Feather } from "@expo/vector-icons";
import type { AVPlaybackStatus } from "expo-av";
import { ResizeMode, Video } from "expo-av";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  GestureResponderEvent,
  LayoutChangeEvent,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import NumericPromptModal from "@/components/BallTracker/NumericPromptModal";
import TrackerControlsSheet from "@/components/BallTracker/TrackerControlsSheet";
import TrackerOverlay, { type TileRect } from "@/components/BallTracker/TrackerOverlay";
import { useColors } from "@/hooks/useColors";
import {
  computeStats,
  fitTrajectory,
  livePreviewTrajectory,
  STAT_DEFS,
  UNIT_TO_YARDS,
  type DistanceUnit,
  type FrameClick,
  type Point,
  type QuadCoeffs,
  type StatKey,
  type Stats,
} from "@/utils/ballTrajectory";

const ORANGE = "#FF5A00"; // TrackMan orange (OpenTrack brand accent)
type Mode = "idle" | "launch" | "apex" | "landing" | "calibrate";

export default function TrackerScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const videoRef = useRef<Video>(null);

  // --- video state ---
  const [videoUri, setVideoUri] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState({ width: 1920, height: 1080 });
  const [durationMs, setDurationMs] = useState(0);
  const [currentMs, setCurrentMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [fps, setFps] = useState(30);
  const [rotation, setRotation] = useState(0); // 0/90/180/270 clockwise, display-only
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });

  const msPerFrame = 1000 / fps;
  const currentFrame = Math.round(currentMs / msPerFrame);
  const frameCount = Math.max(1, Math.round(durationMs / msPerFrame));

  // --- marking state ---
  const [mode, setMode] = useState<Mode>("idle");
  const [launchClicks, setLaunchClicks] = useState<FrameClick[]>([]);
  const [apexClick, setApexClick] = useState<FrameClick | null>(null);
  const [landingClick, setLandingClick] = useState<FrameClick | null>(null);

  const [calDragStart, setCalDragStart] = useState<Point | null>(null);
  const [calDragCurrent, setCalDragCurrent] = useState<Point | null>(null);
  const [calibrationLine, setCalibrationLine] = useState<[Point, Point] | null>(null);
  const [yardsPerPixel, setYardsPerPixel] = useState<number | null>(null);
  const [calibrationDistance, setCalibrationDistance] = useState("");
  const [calibrationUnit, setCalibrationUnit] = useState<DistanceUnit>("yards");
  const [showCalPrompt, setShowCalPrompt] = useState(false);
  const [pendingCalLine, setPendingCalLine] = useState<[Point, Point] | null>(null);

  const [trajectory, setTrajectory] = useState<Map<number, Point>>(new Map());
  const [fitX, setFitX] = useState<QuadCoeffs | null>(null);
  const [fitY, setFitY] = useState<QuadCoeffs | null>(null);
  const [apexFrame, setApexFrame] = useState<number | null>(null);
  const [impactFrame, setImpactFrame] = useState<number | null>(null);
  const [landingFrame, setLandingFrame] = useState<number | null>(null);
  const [stats, setStats] = useState<Stats>({});
  const [warnings, setWarnings] = useState<Set<StatKey>>(new Set());
  const [overrides, setOverrides] = useState<Partial<Record<StatKey, number>>>({});

  const [showRing, setShowRing] = useState(true);
  const [visibleTiles, setVisibleTiles] = useState<Set<StatKey>>(new Set(Object.keys(STAT_DEFS) as StatKey[]));
  const [tileRects, setTileRects] = useState<TileRect[]>([]);

  const [showControls, setShowControls] = useState(false);
  const [statusText, setStatusText] = useState("Load a video to begin.");
  const [editingStat, setEditingStat] = useState<StatKey | null>(null);

  // --- rotation helpers (normalized-coordinate mapping, aspect-independent) ---
  const rotatedToVideo = useCallback((p: Point): Point => {
    switch (rotation) {
      case 90: return { x: p.y, y: 1 - p.x };
      case 180: return { x: 1 - p.x, y: 1 - p.y };
      case 270: return { x: 1 - p.y, y: p.x };
      default: return p;
    }
  }, [rotation]);

  const videoToRotated = useCallback((p: Point): Point => {
    switch (rotation) {
      case 90: return { x: 1 - p.y, y: p.x };
      case 180: return { x: 1 - p.x, y: 1 - p.y };
      case 270: return { x: p.y, y: 1 - p.x };
      default: return p;
    }
  }, [rotation]);

  const displayIsSwapped = rotation === 90 || rotation === 270;
  const displaySize = displayIsSwapped
    ? { width: naturalSize.height, height: naturalSize.width }
    : naturalSize;

  const scale = videoUri
    ? Math.min(stageSize.width / Math.max(displaySize.width, 1), stageSize.height / Math.max(displaySize.height, 1))
    : 1;
  const dispW = displaySize.width * scale;
  const dispH = displaySize.height * scale;
  const rawW = naturalSize.width * scale;
  const rawH = naturalSize.height * scale;

  // --- rotated trajectory / marks projected for the overlay ---
  const rotatedTrajectory = useMemo(() => {
    const m = new Map<number, Point>();
    trajectory.forEach((v, k) => m.set(k, videoToRotated(v)));
    return m;
  }, [trajectory, videoToRotated]);
  const rotatedLaunchClicks = useMemo(() => launchClicks.map((c) => ({ frame: c.frame, point: videoToRotated(c.point) })), [launchClicks, videoToRotated]);
  const rotatedApex = useMemo(() => apexClick && { frame: apexClick.frame, point: videoToRotated(apexClick.point) }, [apexClick, videoToRotated]);
  const rotatedLanding = useMemo(() => landingClick && { frame: landingClick.frame, point: videoToRotated(landingClick.point) }, [landingClick, videoToRotated]);
  const rotatedCalLine = useMemo<[Point, Point] | null>(
    () => calibrationLine && [videoToRotated(calibrationLine[0]), videoToRotated(calibrationLine[1])],
    [calibrationLine, videoToRotated],
  );

  const displayValue = useCallback((key: StatKey) => overrides[key] ?? stats[key], [overrides, stats]);
  const isWarning = useCallback((key: StatKey) => overrides[key] === undefined && warnings.has(key), [overrides, warnings]);
  const hasOverride = useCallback((key: StatKey) => overrides[key] !== undefined, [overrides]);

  // --- video import ---
  const pickVideo = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== "granted") {
      setStatusText("Photo library access is needed to import a video.");
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["videos"], quality: 1 });
    if (result.canceled || !result.assets[0]) return;
    setVideoUri(result.assets[0].uri);
    setDurationMs(0);
    setCurrentMs(0);
    setIsPlaying(false);
    setRotation(0);
    resetMarks();
    setYardsPerPixel(null);
    setCalibrationLine(null);
    setStatusText("Video loaded. Calibrate, then step to impact and click the ball.");
    setShowControls(false);
  };

  const onStatus = (status: AVPlaybackStatus) => {
    if (!status.isLoaded) return;
    setDurationMs(status.durationMillis ?? 0);
    setCurrentMs(status.positionMillis ?? 0);
    setIsPlaying(status.isPlaying);
  };

  const seekToFrame = async (frame: number) => {
    const clamped = Math.max(0, Math.min(frame, frameCount - 1));
    const ms = clamped * msPerFrame;
    setCurrentMs(ms);
    await videoRef.current?.setPositionAsync(ms, { toleranceMillisBefore: 0, toleranceMillisAfter: 0 });
  };

  const stepFrame = async (delta: number) => {
    await videoRef.current?.pauseAsync();
    Haptics.selectionAsync();
    await seekToFrame(currentFrame + delta);
  };

  const togglePlay = async () => {
    if (isPlaying) {
      await videoRef.current?.pauseAsync();
    } else {
      if (currentFrame >= frameCount - 1) await seekToFrame(0);
      await videoRef.current?.playAsync();
    }
  };

  // --- gesture handling on the stage ---
  const toNormalized = (evt: GestureResponderEvent): Point | null => {
    if (!dispW || !dispH) return null;
    const { locationX, locationY } = evt.nativeEvent;
    return { x: Math.min(1, Math.max(0, locationX / dispW)), y: Math.min(1, Math.max(0, locationY / dispH)) };
  };

  const hitTile = (evt: GestureResponderEvent): StatKey | null => {
    const { locationX, locationY } = evt.nativeEvent;
    const hit = tileRects.find((r) => locationX >= r.x && locationX <= r.x + r.w && locationY >= r.y && locationY <= r.y + r.h);
    return hit?.key ?? null;
  };

  const onStageTouchStart = (evt: GestureResponderEvent) => {
    if (mode !== "calibrate") return;
    const rp = toNormalized(evt);
    if (!rp) return;
    setCalDragStart(rp);
    setCalDragCurrent(rp);
  };

  const onStageTouchMove = (evt: GestureResponderEvent) => {
    if (mode !== "calibrate" || !calDragStart) return;
    const rp = toNormalized(evt);
    if (rp) setCalDragCurrent(rp);
  };

  const onStageTouchEnd = (evt: GestureResponderEvent) => {
    const tileKey = apexFrame !== null && currentFrame >= apexFrame ? hitTile(evt) : null;
    if (tileKey) {
      beginEdit(tileKey);
      return;
    }
    const rp = toNormalized(evt);
    if (!rp) return;
    const videoPt = rotatedToVideo(rp);

    if (mode === "calibrate") {
      finishCalibration();
      return;
    }
    if (mode === "launch") {
      recordLaunchClick(videoPt);
    } else if (mode === "apex") {
      recordApex(videoPt);
    } else if (mode === "landing") {
      recordLanding(videoPt);
    }
  };

  // --- marking ---
  const resetMarks = () => {
    setLaunchClicks([]);
    setApexClick(null);
    setLandingClick(null);
    setTrajectory(new Map());
    setFitX(null);
    setFitY(null);
    setApexFrame(null);
    setImpactFrame(null);
    setLandingFrame(null);
    setStats({});
    setWarnings(new Set());
    setOverrides({});
    setMode("idle");
  };

  const refreshLivePreview = (launch: FrameClick[], apex: FrameClick | null, landing: FrameClick | null) => {
    setTrajectory(livePreviewTrajectory(launch, apex, landing));
  };

  const recordLaunchClick = async (p: Point) => {
    await videoRef.current?.pauseAsync();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const next = [...launchClicks, { frame: currentFrame, point: p }].sort((a, b) => a.frame - b.frame);
    setLaunchClicks(next);
    refreshLivePreview(next, apexClick, landingClick);
    setStatusText(`Launch click ${next.length} recorded on frame ${currentFrame}.`);
    if (currentFrame < frameCount - 1) await seekToFrame(currentFrame + 1);
  };

  const recordApex = async (p: Point) => {
    await videoRef.current?.pauseAsync();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const click = { frame: currentFrame, point: p };
    setApexClick(click);
    refreshLivePreview(launchClicks, click, landingClick);
    setStatusText(`Apex marked on frame ${currentFrame}.`);
  };

  const recordLanding = async (p: Point) => {
    await videoRef.current?.pauseAsync();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const click = { frame: currentFrame, point: p };
    setLandingClick(click);
    refreshLivePreview(launchClicks, apexClick, click);
    setStatusText(`Landing marked on frame ${currentFrame}.`);
  };

  // --- calibration ---
  const finishCalibration = () => {
    const s = calDragStart, c = calDragCurrent;
    setCalDragStart(null);
    setCalDragCurrent(null);
    if (!s || !c) return;
    const lenPx = Math.hypot((c.x - s.x) * dispW, (c.y - s.y) * dispH);
    if (lenPx < 5) {
      setStatusText("Calibration line too short — drag a longer line.");
      return;
    }
    // stored in ORIGINAL video space so rotating later doesn't move it
    const videoLine: [Point, Point] = [rotatedToVideo(s), rotatedToVideo(c)];
    setPendingCalLine(videoLine);
    const val = parseFloat(calibrationDistance);
    if (!Number.isNaN(val) && val > 0) {
      applyCalibration(videoLine, lenPx, val);
    } else {
      setShowCalPrompt(true);
    }
  };

  const applyCalibration = (line: [Point, Point], lenPx: number, value: number) => {
    const yards = value * UNIT_TO_YARDS[calibrationUnit];
    setYardsPerPixel(yards / lenPx);
    setCalibrationLine(line);
    setPendingCalLine(null);
    setMode("idle");
    if (trajectory.size > 0 && fitX && fitY && launchClicks.length && apexClick && landingClick) {
      const { stats: s, warnings: w } = computeStats(launchClicks, apexClick, landingClick, fitX, fitY, fps, yards / lenPx);
      setStats(s);
      setWarnings(w);
    }
    setStatusText("Calibration saved.");
  };

  // --- track / clear ---
  const trackShot = () => {
    if (launchClicks.length < 3) {
      setStatusText("Click the ball on at least 3 frames starting at impact.");
      return;
    }
    if (!apexClick || !landingClick) {
      setStatusText("Mark both the Apex and the Landing Point before tracking.");
      return;
    }
    const f0 = launchClicks[0].frame;
    const fLastLaunch = launchClicks[launchClicks.length - 1].frame;
    if (!(f0 < apexClick.frame && apexClick.frame < landingClick.frame) || apexClick.frame <= fLastLaunch) {
      setStatusText("Frames must be ordered: launch clicks → apex → landing.");
      return;
    }

    const result = fitTrajectory(launchClicks, apexClick, landingClick, fps);
    setTrajectory(result.trajectory);
    setFitX(result.fitX);
    setFitY(result.fitY);
    setImpactFrame(result.impactFrame);
    setApexFrame(result.apexFrame);
    setLandingFrame(result.landingFrame);

    const { stats: s, warnings: w } = computeStats(launchClicks, apexClick, landingClick, result.fitX, result.fitY, fps, yardsPerPixel);
    setStats(s);
    setWarnings(w);
    setMode("idle");
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);

    if (yardsPerPixel === null) {
      setStatusText("Shot tracked — calibrate for real-world numbers, or tap a tile to type your own.");
    } else if (w.size > 0) {
      setStatusText("Shot tracked, but some values look implausible — check calibration or override.");
    } else {
      setStatusText("Shot tracked. Press play to watch the trace.");
    }
    seekToFrame(result.impactFrame);
    setShowControls(false);
  };

  const clearMarks = () => {
    resetMarks();
    setStatusText("Marks and track cleared.");
  };

  // --- stat editing ---
  const beginEdit = (key: StatKey) => setEditingStat(key);
  const commitEdit = (raw: string) => {
    if (!editingStat) return;
    const v = parseFloat(raw);
    if (!Number.isNaN(v)) {
      setOverrides((prev) => ({ ...prev, [editingStat]: v }));
      setStatusText(`${STAT_DEFS[editingStat].label} overridden to ${raw} ${STAT_DEFS[editingStat].unit}.`);
    }
    setEditingStat(null);
  };
  const clearEdit = () => {
    if (editingStat) setOverrides((prev) => { const next = { ...prev }; delete next[editingStat]; return next; });
    setEditingStat(null);
  };

  const onStageLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setStageSize({ width, height });
  };

  return (
    <View style={[styles.root, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      {/* header */}
      <View style={[styles.header, { borderColor: colors.border }]}>
        <Text style={[styles.title, { color: colors.text }]}>
          OPEN<Text style={{ color: ORANGE }}>TRACK</Text>
        </Text>
        <Pressable onPress={() => setShowControls(true)} style={[styles.gearBtn, { borderColor: colors.border }]}>
          <Feather name="sliders" size={16} color={colors.text} />
        </Pressable>
      </View>

      {/* stage */}
      <View style={styles.stageWrap} onLayout={onStageLayout}>
        {videoUri ? (
          <View
            style={{ width: dispW, height: dispH, alignSelf: "center", marginTop: (stageSize.height - dispH) / 2 }}
            onStartShouldSetResponder={() => true}
            onMoveShouldSetResponder={() => mode === "calibrate"}
            onResponderGrant={onStageTouchStart}
            onResponderMove={onStageTouchMove}
            onResponderRelease={onStageTouchEnd}
          >
            <View style={{ width: dispW, height: dispH, overflow: "hidden" }}>
              <View
                style={{
                  width: rawW, height: rawH,
                  position: "absolute",
                  left: (dispW - rawW) / 2, top: (dispH - rawH) / 2,
                  transform: [{ rotate: `${rotation}deg` }],
                }}
              >
                <Video
                  ref={videoRef}
                  source={{ uri: videoUri }}
                  style={{ width: rawW, height: rawH }}
                  resizeMode={ResizeMode.CONTAIN}
                  onPlaybackStatusUpdate={onStatus}
                  onReadyForDisplay={(e: any) => {
                    const n = e?.naturalSize;
                    if (n?.width && n?.height) setNaturalSize({ width: n.width, height: n.height });
                  }}
                  useNativeControls={false}
                />
              </View>
            </View>
            <TrackerOverlay
              width={dispW}
              height={dispH}
              mode={mode}
              currentFrame={currentFrame}
              launchClicks={rotatedLaunchClicks}
              apexClick={rotatedApex}
              landingClick={rotatedLanding}
              calibrationLine={rotatedCalLine}
              calDrag={calDragStart && calDragCurrent ? [calDragStart, calDragCurrent] : null}
              trajectory={rotatedTrajectory}
              showRing={showRing}
              visibleTiles={visibleTiles}
              apexFrame={apexFrame}
              displayValue={displayValue}
              isWarning={isWarning}
              overrideSet={new Set(Object.keys(overrides) as StatKey[])}
              onTileRectsChange={setTileRects}
            />
          </View>
        ) : (
          <View style={styles.emptyState}>
            <Text style={[styles.emptyTitle, { color: ORANGE }]}>OPENTRACK STUDIO</Text>
            <Text style={[styles.emptySubtitle, { color: colors.mutedForeground }]}>Choose a swing video to begin</Text>
            <Pressable style={styles.primaryBtn} onPress={pickVideo}>
              <Feather name="upload" size={16} color="black" />
              <Text style={styles.primaryBtnText}>Choose Video</Text>
            </Pressable>
          </View>
        )}
      </View>

      {/* transport */}
      <View style={[styles.transport, { borderColor: colors.border, paddingBottom: insets.bottom + 8 }]}>
        <View style={styles.transportRow}>
          <Pressable style={[styles.transportBtn, { borderColor: colors.border }]} onPress={() => stepFrame(-1)} disabled={!videoUri}>
            <Feather name="skip-back" size={16} color={colors.text} />
          </Pressable>
          <Pressable style={styles.playBtn} onPress={togglePlay} disabled={!videoUri}>
            <Feather name={isPlaying ? "pause" : "play"} size={18} color="black" />
          </Pressable>
          <Pressable style={[styles.transportBtn, { borderColor: colors.border }]} onPress={() => stepFrame(1)} disabled={!videoUri}>
            <Feather name="skip-forward" size={16} color={colors.text} />
          </Pressable>
          <Text style={[styles.frameText, { color: colors.mutedForeground }]}>
            frame {currentFrame} / {Math.max(0, frameCount - 1)}
          </Text>
        </View>
        <Text style={[styles.statusText, { color: colors.mutedForeground }]} numberOfLines={2}>{statusText}</Text>
      </View>

      <TrackerControlsSheet
        visible={showControls}
        onClose={() => setShowControls(false)}
        onPickVideo={pickVideo}
        videoInfo={videoUri ? `${naturalSize.width}×${naturalSize.height} · ${fps} fps · ${frameCount} frames` : null}
        rotation={rotation}
        onRotateLeft={() => setRotation((r) => (r + 270) % 360)}
        onRotateRight={() => setRotation((r) => (r + 90) % 360)}
        mode={mode}
        onSetMode={setMode}
        calibrationDistance={calibrationDistance}
        onCalibrationDistanceChange={setCalibrationDistance}
        calibrationUnit={calibrationUnit}
        onCalibrationUnitChange={setCalibrationUnit}
        yardsPerPixel={yardsPerPixel}
        launchCount={launchClicks.length}
        apexFrame={apexClick?.frame ?? null}
        landingFrame={landingClick?.frame ?? null}
        onTrack={trackShot}
        onClear={clearMarks}
        showRing={showRing}
        onToggleRing={setShowRing}
        visibleTiles={visibleTiles}
        onToggleTile={(key, on) => setVisibleTiles((prev) => {
          const next = new Set(prev);
          if (on) next.add(key); else next.delete(key);
          return next;
        })}
        displayValue={displayValue}
        isWarning={isWarning}
        hasOverride={hasOverride}
        onEditStat={beginEdit}
      />

      <NumericPromptModal
        visible={showCalPrompt}
        title="Calibration distance"
        message={`Enter the real-world length of the line you drew, in ${calibrationUnit}.`}
        placeholder="e.g. 45"
        onCancel={() => { setShowCalPrompt(false); setPendingCalLine(null); }}
        onSubmit={(raw) => {
          setShowCalPrompt(false);
          const val = parseFloat(raw);
          if (pendingCalLine && !Number.isNaN(val) && val > 0) {
            const lenPx = Math.hypot(
              (videoToRotated(pendingCalLine[1]).x - videoToRotated(pendingCalLine[0]).x) * dispW,
              (videoToRotated(pendingCalLine[1]).y - videoToRotated(pendingCalLine[0]).y) * dispH,
            );
            applyCalibration(pendingCalLine, lenPx, val);
          } else {
            setStatusText("Calibration cancelled — no valid distance.");
            setPendingCalLine(null);
          }
        }}
      />

      <NumericPromptModal
        visible={editingStat !== null}
        title={editingStat ? STAT_DEFS[editingStat].label : ""}
        initialValue={editingStat && displayValue(editingStat) !== undefined ? String(displayValue(editingStat)) : ""}
        placeholder={editingStat ? STAT_DEFS[editingStat].unit : ""}
        onCancel={() => setEditingStat(null)}
        onSubmit={commitEdit}
        onClear={editingStat && hasOverride(editingStat) ? clearEdit : undefined}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 16, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: 15, fontWeight: "800", letterSpacing: 0.5 },
  gearBtn: { borderWidth: 1, borderRadius: 8, padding: 8 },
  stageWrap: { flex: 1 },
  emptyState: { flex: 1, alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 24 },
  emptyTitle: { fontSize: 18, fontWeight: "800" },
  emptySubtitle: { fontSize: 13 },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: ORANGE, borderRadius: 9, paddingVertical: 11, paddingHorizontal: 18, marginTop: 14 },
  primaryBtnText: { color: "black", fontWeight: "700", fontSize: 14 },
  transport: { borderTopWidth: StyleSheet.hairlineWidth, paddingHorizontal: 14, paddingTop: 10, gap: 4 },
  transportRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  transportBtn: { borderWidth: 1, borderRadius: 8, padding: 10 },
  playBtn: { backgroundColor: ORANGE, borderRadius: 9, paddingVertical: 10, paddingHorizontal: 16 },
  frameText: { fontSize: 11, marginLeft: 4, fontVariant: ["tabular-nums"] },
  statusText: { fontSize: 11 },
});
