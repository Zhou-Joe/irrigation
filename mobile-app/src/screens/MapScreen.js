import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Alert, Button } from 'react-native';
import MapView, { Polygon } from 'react-native-maps';
import * as Location from 'expo-location';

// Predefined zone data for the horticulture area
const ZONE_DATA = [
  {
    id: 'zone-1',
    name: 'Zone A - Garden Beds',
    coordinates: [
      { latitude: 37.78825, longitude: -122.4324 },
      { latitude: 37.78845, longitude: -122.4314 },
      { latitude: 37.78785, longitude: -122.4310 },
      { latitude: 37.78765, longitude: -122.4320 },
    ],
    color: 'rgba(52, 191, 85, 0.5)',
  },
  {
    id: 'zone-2',
    name: 'Zone B - Orchard',
    coordinates: [
      { latitude: 37.78925, longitude: -122.4334 },
      { latitude: 37.78945, longitude: -122.4324 },
      { latitude: 37.78885, longitude: -122.4320 },
      { latitude: 37.78865, longitude: -122.4330 },
    ],
    color: 'rgba(52, 155, 191, 0.5)',
  },
  {
    id: 'zone-3',
    name: 'Zone C - Greenhouse',
    coordinates: [
      { latitude: 37.78725, longitude: -122.4314 },
      { latitude: 37.78745, longitude: -122.4304 },
      { latitude: 37.78685, longitude: -122.4300 },
      { latitude: 37.78665, longitude: -122.4310 },
    ],
    color: 'rgba(191, 155, 52, 0.5)',
  },
];

export default function MapScreen({ navigation }) {
  const [location, setLocation] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    (async () => {
      // Request location permission
      let { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setErrorMsg('Permission to access location was denied');
        return;
      }

      // Get current location
      let currentLocation = await Location.getCurrentPositionAsync({});
      setLocation(currentLocation);
    })();
  }, []);

  const handleZonePress = (zone) => {
    setSelectedZone(zone);
  };

  const handleLogWork = () => {
    if (!selectedZone) {
      Alert.alert('No Zone Selected', 'Please tap on a zone polygon first.');
      return;
    }
    navigation.navigate('WorkLog', { zone: selectedZone });
  };

  const initialRegion = location
    ? {
        latitude: location.coords.latitude,
        longitude: location.coords.longitude,
        latitudeDelta: 0.01,
        longitudeDelta: 0.01,
      }
    : {
        latitude: 37.78825,
        longitude: -122.4324,
        latitudeDelta: 0.02,
        longitudeDelta: 0.02,
      };

  return (
    <View style={styles.container}>
      <MapView style={styles.map} initialRegion={initialRegion} showsUserLocation>
        {ZONE_DATA.map((zone) => (
          <Polygon
            key={zone.id}
            coordinates={zone.coordinates}
            fillColor={zone.color}
            strokeColor={selectedZone?.id === zone.id ? '#000' : '#333'}
            strokeWidth={selectedZone?.id === zone.id ? 3 : 1}
            onPress={() => handleZonePress(zone)}
          />
        ))}
      </MapView>
      <View style={styles.buttonContainer}>
        <Button
          title="Log Work"
          onPress={handleLogWork}
          disabled={!selectedZone}
        />
      </View>
      {selectedZone && (
        <View style={styles.infoContainer}>
          <View style={styles.infoBox}>
            <Text style={styles.zoneName}>{selectedZone.name}</Text>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  map: {
    width: '100%',
    height: '100%',
  },
  buttonContainer: {
    position: 'absolute',
    bottom: 80,
    left: 20,
    right: 20,
  },
  infoContainer: {
    position: 'absolute',
    bottom: 140,
    left: 20,
    right: 20,
  },
  infoBox: {
    backgroundColor: 'white',
    padding: 15,
    borderRadius: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 3.84,
    elevation: 5,
  },
  zoneName: {
    fontSize: 16,
    fontWeight: 'bold',
    textAlign: 'center',
  },
});
