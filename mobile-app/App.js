import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import MapScreen from './src/screens/MapScreen';
import WorkLogScreen from './src/screens/WorkLogScreen';

const Stack = createStackNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Map">
        <Stack.Screen
          name="Map"
          component={MapScreen}
          options={{ title: 'Irrigation Zones' }}
        />
        <Stack.Screen
          name="WorkLog"
          component={WorkLogScreen}
          options={{ title: 'Log Work' }}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
