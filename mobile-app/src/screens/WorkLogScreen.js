import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  Alert,
  ScrollView,
} from 'react-native';
import { uploadWorkLog } from '../services/api';
import { queueWorkLog } from '../services/offline-queue';

const WORK_TYPES = [
  { id: 'planting', label: 'Planting' },
  { id: 'watering', label: 'Watering' },
  { id: 'pruning', label: 'Pruning' },
  { id: 'fertilizing', label: 'Fertilizing' },
  { id: 'pest_control', label: 'Pest Control' },
  { id: 'harvesting', label: 'Harvesting' },
  { id: 'maintenance', label: 'Maintenance' },
  { id: 'other', label: 'Other' },
];

export default function WorkLogScreen({ route, navigation }) {
  const { zone } = route.params || {};
  const [workType, setWorkType] = useState('');
  const [workOrder, setWorkOrder] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!workType) {
      Alert.alert('Required Field', 'Please select a work type.');
      return;
    }

    setSubmitting(true);

    const workLog = {
      zoneId: zone?.id,
      zoneName: zone?.name,
      workType,
      workOrder: workOrder || null,
      notes,
      timestamp: new Date().toISOString(),
      location: zone?.coordinates?.[0],
    };

    try {
      // Try to upload immediately
      await uploadWorkLog(workLog);
      Alert.alert('Success', 'Work log uploaded successfully!', [
        { text: 'OK', onPress: () => navigation.goBack() },
      ]);
    } catch (error) {
      // If upload fails (offline), queue it
      await queueWorkLog(workLog);
      Alert.alert(
        'Offline Mode',
        'Work log saved to queue. It will be uploaded when online.',
        [{ text: 'OK', onPress: () => navigation.goBack() }]
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.content}>
        {zone && (
          <View style={styles.zoneInfo}>
            <Text style={styles.zoneLabel}>Selected Zone:</Text>
            <Text style={styles.zoneName}>{zone.name}</Text>
          </View>
        )}

        <View style={styles.formGroup}>
          <Text style={styles.label}>Work Type *</Text>
          <View style={styles.workTypeContainer}>
            {WORK_TYPES.map((type) => (
              <TouchableOpacity
                key={type.id}
                style={[
                  styles.workTypeButton,
                  workType === type.id && styles.workTypeButtonSelected,
                ]}
                onPress={() => setWorkType(type.id)}
              >
                <Text
                  style={[
                    styles.workTypeText,
                    workType === type.id && styles.workTypeTextSelected,
                  ]}
                >
                  {type.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        <View style={styles.formGroup}>
          <Text style={styles.label}>Work Order (Optional)</Text>
          <TextInput
            style={styles.input}
            placeholder="Enter work order number"
            value={workOrder}
            onChangeText={setWorkOrder}
            autoCapitalize="none"
            autoCorrect={false}
          />
        </View>

        <View style={styles.formGroup}>
          <Text style={styles.label}>Notes</Text>
          <TextInput
            style={[styles.input, styles.textArea]}
            placeholder="Add any additional notes..."
            value={notes}
            onChangeText={setNotes}
            multiline
            numberOfLines={4}
          />
        </View>

        <TouchableOpacity
          style={[styles.submitButton, submitting && styles.submitButtonDisabled]}
          onPress={handleSubmit}
          disabled={submitting}
        >
          <Text style={styles.submitButtonText}>
            {submitting ? 'Submitting...' : 'Submit Work Log'}
          </Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  content: {
    padding: 20,
  },
  zoneInfo: {
    backgroundColor: '#e8f5e9',
    padding: 15,
    borderRadius: 8,
    marginBottom: 20,
  },
  zoneLabel: {
    fontSize: 14,
    color: '#666',
  },
  zoneName: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#2e7d32',
    marginTop: 4,
  },
  formGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
    marginBottom: 8,
  },
  workTypeContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  workTypeButton: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    backgroundColor: '#fff',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#ddd',
    marginRight: 8,
    marginBottom: 8,
  },
  workTypeButtonSelected: {
    backgroundColor: '#4caf50',
    borderColor: '#4caf50',
  },
  workTypeText: {
    fontSize: 14,
    color: '#666',
  },
  workTypeTextSelected: {
    color: '#fff',
    fontWeight: '600',
  },
  input: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
  },
  textArea: {
    height: 100,
    textAlignVertical: 'top',
  },
  submitButton: {
    backgroundColor: '#4caf50',
    paddingVertical: 15,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 10,
  },
  submitButtonDisabled: {
    backgroundColor: '#a5d6a7',
  },
  submitButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
});
