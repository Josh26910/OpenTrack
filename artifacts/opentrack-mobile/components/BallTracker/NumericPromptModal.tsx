import React, { useEffect, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useColors } from "@/hooks/useColors";

type Props = {
  visible: boolean;
  title: string;
  message?: string;
  initialValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  onCancel: () => void;
  onSubmit: (value: string) => void;
  onClear?: () => void;
};

/** Small centered modal with a single numeric text field — used for the
 * calibration-distance prompt and stat-tile value overrides. Android has
 * no Alert.prompt, so this stands in for both platforms. */
export default function NumericPromptModal({
  visible, title, message, initialValue, placeholder, confirmLabel = "Set",
  onCancel, onSubmit, onClear,
}: Props) {
  const colors = useColors();
  const [value, setValue] = useState(initialValue ?? "");

  useEffect(() => {
    if (visible) setValue(initialValue ?? "");
  }, [visible, initialValue]);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
          <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
          {message ? <Text style={[styles.message, { color: colors.mutedForeground }]}>{message}</Text> : null}
          <TextInput
            style={[styles.input, { borderColor: colors.border, color: colors.text, backgroundColor: colors.input }]}
            value={value}
            onChangeText={setValue}
            keyboardType="decimal-pad"
            placeholder={placeholder}
            placeholderTextColor={colors.mutedForeground}
            autoFocus
          />
          <View style={styles.row}>
            {onClear ? (
              <Pressable style={styles.btn} onPress={onClear}>
                <Text style={[styles.btnText, { color: colors.destructive }]}>Clear</Text>
              </Pressable>
            ) : (
              <View style={styles.btn} />
            )}
            <Pressable style={styles.btn} onPress={onCancel}>
              <Text style={[styles.btnText, { color: colors.mutedForeground }]}>Cancel</Text>
            </Pressable>
            <Pressable style={styles.btn} onPress={() => onSubmit(value)}>
              <Text style={[styles.btnText, { color: colors.primary, fontWeight: "700" }]}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "center", alignItems: "center", padding: 24 },
  card: { width: "100%", maxWidth: 340, borderRadius: 14, borderWidth: 1, padding: 18 },
  title: { fontSize: 16, fontWeight: "700", marginBottom: 4 },
  message: { fontSize: 12, marginBottom: 12 },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, marginTop: 8, marginBottom: 14 },
  row: { flexDirection: "row", justifyContent: "flex-end", gap: 18 },
  btn: { paddingVertical: 6, paddingHorizontal: 4 },
  btnText: { fontSize: 14 },
});
