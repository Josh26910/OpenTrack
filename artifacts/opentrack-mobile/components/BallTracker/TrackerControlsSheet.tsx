import { Feather } from "@expo/vector-icons";
import React from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useColors } from "@/hooks/useColors";
import { STAT_DEFS, UNIT_TO_YARDS, type DistanceUnit, type StatKey } from "@/utils/ballTrajectory";

const ORANGE = "#FF5A00"; // TrackMan orange (OpenTrack brand accent)

type Props = {
  visible: boolean;
  onClose: () => void;
  onPickVideo: () => void;
  videoInfo: string | null;
  rotation: number;
  onRotateLeft: () => void;
  onRotateRight: () => void;
  mode: "idle" | "launch" | "apex" | "landing" | "calibrate";
  onSetMode: (m: "idle" | "launch" | "apex" | "landing" | "calibrate") => void;
  calibrationDistance: string;
  onCalibrationDistanceChange: (v: string) => void;
  calibrationUnit: DistanceUnit;
  onCalibrationUnitChange: (u: DistanceUnit) => void;
  yardsPerPixel: number | null;
  launchCount: number;
  apexFrame: number | null;
  landingFrame: number | null;
  onTrack: () => void;
  onClear: () => void;
  showRing: boolean;
  onToggleRing: (v: boolean) => void;
  visibleTiles: Set<StatKey>;
  onToggleTile: (key: StatKey, on: boolean) => void;
  displayValue: (key: StatKey) => number | undefined;
  isWarning: (key: StatKey) => boolean;
  hasOverride: (key: StatKey) => boolean;
  onEditStat: (key: StatKey) => void;
};

export default function TrackerControlsSheet(props: Props) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const units: DistanceUnit[] = Object.keys(UNIT_TO_YARDS) as DistanceUnit[];

  return (
    <Modal visible={props.visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={props.onClose}>
      <View style={[styles.root, { backgroundColor: colors.background }]}>
        <View style={[styles.header, { borderColor: colors.border, paddingTop: insets.top ? 8 : 16 }]}>
          <Text style={[styles.headerTitle, { color: colors.text }]}>OpenTrack Controls</Text>
          <Pressable onPress={props.onClose} hitSlop={12}>
            <Feather name="x" size={22} color={colors.mutedForeground} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }}>
          <Section title="1 · VIDEO" colors={colors}>
            <PrimaryButton label="Choose Video" icon="upload" onPress={props.onPickVideo} />
            {props.videoInfo && <Text style={[styles.caption, { color: colors.mutedForeground }]}>{props.videoInfo}</Text>}
            <View style={styles.row}>
              <IconButton icon="rotate-ccw" colors={colors} onPress={props.onRotateLeft} />
              <Text style={[styles.rotationText, { color: ORANGE }]}>{props.rotation}°</Text>
              <IconButton icon="rotate-cw" colors={colors} onPress={props.onRotateRight} />
            </View>
          </Section>

          <Section title="2 · CALIBRATION" colors={colors}>
            <ModeButton
              label="Draw Calibration Line"
              icon="crosshair"
              active={props.mode === "calibrate"}
              colors={colors}
              onPress={() => props.onSetMode(props.mode === "calibrate" ? "idle" : "calibrate")}
            />
            <View style={styles.row}>
              <TextInput
                style={[styles.input, { flex: 1, borderColor: colors.border, color: colors.text, backgroundColor: colors.input }]}
                value={props.calibrationDistance}
                onChangeText={props.onCalibrationDistanceChange}
                keyboardType="decimal-pad"
                placeholder="Known distance"
                placeholderTextColor={colors.mutedForeground}
              />
              <View style={styles.unitRow}>
                {units.map((u) => (
                  <Pressable
                    key={u}
                    onPress={() => props.onCalibrationUnitChange(u)}
                    style={[
                      styles.unitChip,
                      { borderColor: colors.border },
                      props.calibrationUnit === u && { backgroundColor: ORANGE, borderColor: ORANGE },
                    ]}
                  >
                    <Text style={{ fontSize: 11, color: props.calibrationUnit === u ? "black" : colors.mutedForeground }}>
                      {u}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
            <Text style={[styles.caption, { color: colors.mutedForeground }]}>
              {props.yardsPerPixel !== null
                ? `Calibrated: 1px = ${props.yardsPerPixel.toFixed(4)} yd`
                : "Not calibrated — stats will show '--'"}
            </Text>
          </Section>

          <Section title="3 · MARK THE SHOT" colors={colors}>
            <ModeButton label="Click Ball — Launch Frames" icon="plus-circle" active={props.mode === "launch"} colors={colors}
              onPress={() => props.onSetMode(props.mode === "launch" ? "idle" : "launch")} />
            <Text style={[styles.caption, { color: colors.mutedForeground }]}>Launch clicks: {props.launchCount} (minimum 3)</Text>

            <ModeButton label="Mark Apex" icon="arrow-up" active={props.mode === "apex"} colors={colors}
              onPress={() => props.onSetMode(props.mode === "apex" ? "idle" : "apex")} />
            <Text style={[styles.caption, { color: colors.mutedForeground }]}>
              {props.apexFrame !== null ? `Apex: frame ${props.apexFrame}` : "Apex: not set"}
            </Text>

            <ModeButton label="Mark Landing Point" icon="arrow-down" active={props.mode === "landing"} colors={colors}
              onPress={() => props.onSetMode(props.mode === "landing" ? "idle" : "landing")} />
            <Text style={[styles.caption, { color: colors.mutedForeground }]}>
              {props.landingFrame !== null ? `Landing: frame ${props.landingFrame}` : "Landing: not set"}
            </Text>
          </Section>

          <Section title="4 · TRACK" colors={colors}>
            <PrimaryButton label="Track Shot" icon="target" onPress={props.onTrack} />
            <Pressable style={[styles.widgetBtn, { borderColor: colors.border, marginTop: 8 }]} onPress={props.onClear}>
              <Feather name="x-circle" size={15} color={colors.destructive} />
              <Text style={[styles.widgetBtnText, { color: colors.destructive }]}>Clear Marks & Track</Text>
            </Pressable>
          </Section>

          <Section title="5 · DATA LAYOUT" colors={colors}>
            <ToggleRow label="Tracking ring" value={props.showRing} onChange={props.onToggleRing} colors={colors} />
            {(Object.keys(STAT_DEFS) as StatKey[]).map((key) => (
              <ToggleRow
                key={key}
                label={`Tile — ${STAT_DEFS[key].label}`}
                value={props.visibleTiles.has(key)}
                onChange={(v) => props.onToggleTile(key, v)}
                colors={colors}
              />
            ))}
          </Section>

          <Section title="SHOT DATA" colors={colors}>
            <Text style={[styles.caption, { color: colors.mutedForeground, marginBottom: 8 }]}>
              Tap a tile on the video (once tracked) to override its value.
            </Text>
            {(Object.keys(STAT_DEFS) as StatKey[]).map((key) => {
              const def = STAT_DEFS[key];
              const val = props.displayValue(key);
              return (
                <Pressable
                  key={key}
                  style={[styles.statRow, { backgroundColor: colors.card }]}
                  onPress={() => props.onEditStat(key)}
                >
                  <Text style={[styles.statLabel, { color: ORANGE }]}>{def.label}</Text>
                  <View style={styles.row}>
                    <Text style={{ color: props.isWarning(key) ? ORANGE : colors.text, fontWeight: "700", fontSize: 15 }}>
                      {val === undefined ? `-- ${def.unit}` : `${val.toFixed(def.decimals)} ${def.unit}`}
                    </Text>
                    {props.hasOverride(key) && <Feather name="edit-2" size={11} color={colors.mutedForeground} style={{ marginLeft: 6 }} />}
                  </View>
                </Pressable>
              );
            })}
          </Section>
        </ScrollView>
      </View>
    </Modal>
  );
}

function Section({ title, colors, children }: { title: string; colors: any; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 18 }}>
      <View style={styles.sectionHeaderRow}>
        <Text style={[styles.sectionTitle, { color: ORANGE }]}>{title}</Text>
        <View style={[styles.sectionLine, { backgroundColor: colors.border }]} />
      </View>
      <View style={{ gap: 8, marginTop: 8 }}>{children}</View>
    </View>
  );
}

function PrimaryButton({ label, icon, onPress }: { label: string; icon: any; onPress: () => void }) {
  return (
    <Pressable style={styles.primaryBtn} onPress={onPress}>
      <Feather name={icon} size={16} color="black" />
      <Text style={styles.primaryBtnText}>{label}</Text>
    </Pressable>
  );
}

function ModeButton({ label, icon, active, colors, onPress }: { label: string; icon: any; active: boolean; colors: any; onPress: () => void }) {
  return (
    <Pressable
      style={[styles.widgetBtn, { borderColor: active ? ORANGE : colors.border, backgroundColor: active ? ORANGE : "transparent" }]}
      onPress={onPress}
    >
      <Feather name={icon} size={15} color={active ? "black" : colors.text} />
      <Text style={[styles.widgetBtnText, { color: active ? "black" : colors.text }]}>{label}</Text>
    </Pressable>
  );
}

function IconButton({ icon, colors, onPress }: { icon: any; colors: any; onPress: () => void }) {
  return (
    <Pressable style={[styles.iconBtn, { borderColor: colors.border }]} onPress={onPress}>
      <Feather name={icon} size={16} color={colors.text} />
    </Pressable>
  );
}

function ToggleRow({ label, value, onChange, colors }: { label: string; value: boolean; onChange: (v: boolean) => void; colors: any }) {
  return (
    <View style={styles.toggleRow}>
      <Text style={{ color: colors.text, fontSize: 13 }}>{label}</Text>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: ORANGE, false: colors.border }} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 16, paddingBottom: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: 16, fontWeight: "700" },
  sectionHeaderRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  sectionTitle: { fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  sectionLine: { flex: 1, height: 1 },
  caption: { fontSize: 11 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  unitRow: { flexDirection: "row", gap: 4 },
  unitChip: { paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6, borderWidth: 1 },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 14 },
  rotationText: { fontSize: 14, fontWeight: "700", width: 44, textAlign: "center" },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: ORANGE, borderRadius: 9, paddingVertical: 11 },
  primaryBtnText: { color: "black", fontWeight: "700", fontSize: 14 },
  widgetBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderRadius: 8, borderWidth: 1, paddingVertical: 10 },
  widgetBtnText: { fontWeight: "700", fontSize: 13 },
  iconBtn: { borderWidth: 1, borderRadius: 8, padding: 9 },
  toggleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 4 },
  statRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 10 },
  statLabel: { fontSize: 11, fontWeight: "700" },
});
