import React from "react";
import Svg, { Circle, Line, Rect, Text as SvgText } from "react-native-svg";

import type { FrameClick, Point, StatKey } from "@/utils/ballTrajectory";
import { STAT_DEFS } from "@/utils/ballTrajectory";

const ORANGE = "#FF5A00"; // TrackMan orange (OpenTrack brand accent)
const WARN = "#FFD60A";

export type TileRect = { key: StatKey; x: number; y: number; w: number; h: number };

type Props = {
  width: number;
  height: number;
  mode: "idle" | "launch" | "apex" | "landing" | "calibrate";
  currentFrame: number;
  launchClicks: FrameClick[];
  apexClick: FrameClick | null;
  landingClick: FrameClick | null;
  calibrationLine: [Point, Point] | null;
  calDrag: [Point, Point] | null;
  trajectory: Map<number, Point>;
  showRing: boolean;
  visibleTiles: Set<StatKey>;
  apexFrame: number | null;
  displayValue: (key: StatKey) => number | undefined;
  isWarning: (key: StatKey) => boolean;
  overrideSet: Set<StatKey>;
  onTileRectsChange: (rects: TileRect[]) => void;
};

/** All overlay drawing lives here so the tracker screen stays focused on
 * state/gestures. Coordinates in are all normalized (0..1 of width/height)
 * — the screen owns mapping raw taps into this space. */
export default function TrackerOverlay({
  width, height, mode, currentFrame, launchClicks, apexClick, landingClick,
  calibrationLine, calDrag, trajectory, showRing, visibleTiles, apexFrame,
  displayValue, isWarning, overrideSet, onTileRectsChange,
}: Props) {
  const px = (p: Point) => ({ x: p.x * width, y: p.y * height });

  // --- click markers ---
  const markers: { p: Point; label: string; onFrame: boolean }[] = [];
  launchClicks.forEach((c, i) => markers.push({ p: c.point, label: String(i + 1), onFrame: c.frame === currentFrame }));
  if (apexClick) markers.push({ p: apexClick.point, label: "A", onFrame: apexClick.frame === currentFrame });
  if (landingClick) markers.push({ p: landingClick.point, label: "L", onFrame: landingClick.frame === currentFrame });

  // --- tracking ring ---
  const ringPoint = trajectory.get(currentFrame);
  const ringR = Math.max(9, width / 45);

  // --- stat tiles ---
  const visible = (Object.keys(STAT_DEFS) as StatKey[]).filter((k) => visibleTiles.has(k));
  const tilesVisible = apexFrame !== null && currentFrame >= apexFrame && visible.length > 0;
  let tileRects: TileRect[] = [];
  if (tilesVisible) {
    const gap = Math.max(6, width * 0.02);
    const n = visible.length;
    let tileW = Math.min(width * 0.26, (width - (n + 1) * gap) / Math.max(n, 1));
    tileW = Math.max(78, tileW);
    const tileH = tileW * 0.5;
    const totalW = n * tileW + (n - 1) * gap;
    const x0 = (width - totalW) / 2;
    const y0 = Math.max(8, height * 0.03);
    tileRects = visible.map((key, i) => ({ key, x: x0 + i * (tileW + gap), y: y0, w: tileW, h: tileH }));
  }
  React.useEffect(() => {
    onTileRectsChange(tileRects);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(tileRects)]);
  const fade = apexFrame !== null ? Math.min(1, (currentFrame - apexFrame + 1) / 10) : 0;

  return (
    <Svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }} pointerEvents="none">
      {/* calibration */}
      {mode === "calibrate" && calDrag && (() => {
        const p1 = px(calDrag[0]), p2 = px(calDrag[1]);
        const lenPx = Math.hypot(calDrag[1].x * width - calDrag[0].x * width, calDrag[1].y * height - calDrag[0].y * height);
        return (
          <>
            <Line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="black" strokeWidth={5} strokeOpacity={0.8} />
            <Line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={ORANGE} strokeWidth={2} />
            <Circle cx={p1.x} cy={p1.y} r={6} fill={ORANGE} />
            <Circle cx={p2.x} cy={p2.y} r={6} fill={ORANGE} />
            <SvgText x={(p1.x + p2.x) / 2} y={(p1.y + p2.y) / 2 - 14} fill="white" fontSize={12} textAnchor="middle">
              {Math.round(lenPx)}px
            </SvgText>
          </>
        );
      })()}
      {mode === "calibrate" && !calDrag && calibrationLine && (() => {
        const p1 = px(calibrationLine[0]), p2 = px(calibrationLine[1]);
        return <Line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={ORANGE} strokeOpacity={0.6} strokeWidth={1} />;
      })()}

      {/* click markers */}
      {markers.map((m, i) => {
        const p = px(m.p);
        const r = m.onFrame ? Math.max(7, width / 90) : Math.max(2, width / 260);
        return (
          <React.Fragment key={i}>
            {m.onFrame && <Circle cx={p.x} cy={p.y} r={r + 3} stroke="black" strokeWidth={r} fill="none" />}
            <Circle cx={p.x} cy={p.y} r={r} fill={m.onFrame ? ORANGE : "#5A6E82"} stroke={m.onFrame ? "white" : "none"} strokeWidth={1} />
            {m.onFrame && (
              <SvgText x={p.x + r + 10} y={p.y + 4} fill={ORANGE} fontSize={12} fontWeight="bold">
                {m.label}
              </SvgText>
            )}
          </React.Fragment>
        );
      })}

      {/* tracking ring */}
      {showRing && ringPoint && (() => {
        const p = px(ringPoint);
        if (p.x + ringR < 0 || p.x - ringR > width || p.y + ringR < 0 || p.y - ringR > height) return null;
        return (
          <>
            <Circle cx={p.x} cy={p.y} r={ringR} stroke="black" strokeWidth={5} fill="none" />
            <Circle cx={p.x} cy={p.y} r={ringR} stroke={ORANGE} strokeWidth={3} fill="none" />
            <Circle cx={p.x} cy={p.y} r={2} fill="white" />
          </>
        );
      })()}

      {/* stat tiles */}
      {tilesVisible && tileRects.map((rect) => {
        const def = STAT_DEFS[rect.key];
        const val = displayValue(rect.key);
        const vtext = val === undefined ? "--" : val.toFixed(def.decimals);
        const cx = rect.x + rect.w / 2;
        return (
          <React.Fragment key={rect.key}>
            <Rect x={rect.x} y={rect.y} width={rect.w} height={rect.h} rx={6} fill="black" fillOpacity={0.78 * fade} />
            <Rect x={rect.x} y={rect.y} width={Math.max(3, rect.w / 40)} height={rect.h} fill={ORANGE} fillOpacity={fade} />
            <SvgText x={cx} y={rect.y + rect.h * 0.24} fill={ORANGE} fillOpacity={fade} fontSize={9} fontWeight="bold" textAnchor="middle">
              {def.label}
            </SvgText>
            <SvgText x={cx} y={rect.y + rect.h * 0.58} fill="white" fillOpacity={fade} fontSize={rect.w * 0.19} fontWeight="bold" textAnchor="middle">
              {vtext}
            </SvgText>
            <SvgText x={cx} y={rect.y + rect.h * 0.85} fill="#9A9AA0" fillOpacity={fade} fontSize={8} textAnchor="middle">
              {def.unit}
            </SvgText>
            {isWarning(rect.key) && !overrideSet.has(rect.key) && (
              <Circle cx={rect.x + rect.w - 12} cy={rect.y + 12} r={7} fill={WARN} fillOpacity={fade} />
            )}
          </React.Fragment>
        );
      })}
    </Svg>
  );
}
