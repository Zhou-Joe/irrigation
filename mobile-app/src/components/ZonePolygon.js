import React from 'react';
import { Polygon } from 'react-native-maps';

/**
 * ZonePolygon - Helper component for rendering zone polygons on the map
 *
 * @param {Object} props
 * @param {string} props.id - Unique zone identifier
 * @param {Array} props.coordinates - Array of {latitude, longitude} points
 * @param {string} props.color - Fill color for the polygon
 * @param {boolean} props.selected - Whether this zone is currently selected
 * @param {Function} props.onPress - Callback when polygon is pressed
 * @param {string} props.name - Zone name for accessibility
 */
export default function ZonePolygon({
  id,
  coordinates,
  color = 'rgba(52, 191, 85, 0.5)',
  selected = false,
  onPress,
  name,
}) {
  return (
    <Polygon
      identifier={id}
      coordinates={coordinates}
      fillColor={color}
      strokeColor={selected ? '#000000' : '#333333'}
      strokeWidth={selected ? 3 : 1}
      accessible={true}
      accessibilityLabel={name || `Zone ${id}`}
      onPress={onPress}
    />
  );
}

/**
 * Calculate the center point of a polygon
 * @param {Array} coordinates - Array of {latitude, longitude} points
 * @returns {Object} - Center point with latitude and longitude
 */
export function getPolygonCenter(coordinates) {
  if (!coordinates || coordinates.length === 0) {
    return { latitude: 0, longitude: 0 };
  }

  const sum = coordinates.reduce(
    (acc, coord) => ({
      latitude: acc.latitude + coord.latitude,
      longitude: acc.longitude + coord.longitude,
    }),
    { latitude: 0, longitude: 0 }
  );

  return {
    latitude: sum.latitude / coordinates.length,
    longitude: sum.longitude / coordinates.length,
  };
}

/**
 * Calculate region for map to fit a polygon
 * @param {Array} coordinates - Array of {latitude, longitude} points
 * @param {number} padding - Padding around the polygon in degrees
 * @returns {Object} - Region object for MapView
 */
export function getPolygonRegion(coordinates, padding = 0.005) {
  if (!coordinates || coordinates.length === 0) {
    return {
      latitude: 0,
      longitude: 0,
      latitudeDelta: 0.01,
      longitudeDelta: 0.01,
    };
  }

  const latitudes = coordinates.map((c) => c.latitude);
  const longitudes = coordinates.map((c) => c.longitude);

  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLng = Math.min(...longitudes);
  const maxLng = Math.max(...longitudes);

  const latDelta = maxLat - minLat + padding * 2;
  const lngDelta = maxLng - minLng + padding * 2;

  return {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLng + maxLng) / 2,
    latitudeDelta: Math.max(latDelta, 0.01),
    longitudeDelta: Math.max(lngDelta, 0.01),
  };
}
