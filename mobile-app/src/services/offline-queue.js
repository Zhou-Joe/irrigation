import AsyncStorage from '@react-native-async-storage/async-storage';

const QUEUE_KEY = '@horticulture_offline_queue';
const MAX_QUEUE_SIZE = 100;

/**
 * Initialize the offline queue
 * @returns {Promise<Array>} - Current queue contents
 */
export async function initQueue() {
  try {
    const queue = await AsyncStorage.getItem(QUEUE_KEY);
    if (queue === null) {
      await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify([]));
      return [];
    }
    return JSON.parse(queue);
  } catch (error) {
    console.error('Error initializing queue:', error);
    return [];
  }
}

/**
 * Get all items in the queue
 * @returns {Promise<Array>} - Array of queued items
 */
export async function getQueue() {
  try {
    const queue = await AsyncStorage.getItem(QUEUE_KEY);
    return queue ? JSON.parse(queue) : [];
  } catch (error) {
    console.error('Error getting queue:', error);
    return [];
  }
}

/**
 * Add an item to the queue
 * @param {Object} item - Item to add to queue
 * @returns {Promise<number>} - New queue length
 */
export async function enqueue(item) {
  try {
    const queue = await getQueue();

    // Prevent queue from growing too large
    if (queue.length >= MAX_QUEUE_SIZE) {
      // Remove oldest items
      queue.splice(0, queue.length - MAX_QUEUE_SIZE + 1);
    }

    const queuedItem = {
      ...item,
      queuedAt: new Date().toISOString(),
      id: generateId(),
    };

    queue.push(queuedItem);
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    return queue.length;
  } catch (error) {
    console.error('Error enqueueing item:', error);
    throw error;
  }
}

/**
 * Remove an item from the queue by ID
 * @param {string} itemId - ID of item to remove
 * @returns {Promise<boolean>} - True if item was removed
 */
export async function dequeue(itemId) {
  try {
    const queue = await getQueue();
    const filtered = queue.filter((item) => item.id !== itemId);

    if (filtered.length === queue.length) {
      return false; // Item not found
    }

    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(filtered));
    return true;
  } catch (error) {
    console.error('Error dequeuing item:', error);
    throw error;
  }
}

/**
 * Clear the entire queue
 * @returns {Promise<void>}
 */
export async function clearQueue() {
  try {
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify([]));
  } catch (error) {
    console.error('Error clearing queue:', error);
    throw error;
  }
}

/**
 * Get queue statistics
 * @returns {Promise<Object>} - Queue stats
 */
export async function getQueueStats() {
  try {
    const queue = await getQueue();
    const now = new Date();

    // Count items by age
    const lastHour = queue.filter(
      (item) => now - new Date(item.queuedAt) < 3600000
    ).length;
    const lastDay = queue.filter(
      (item) => now - new Date(item.queuedAt) < 86400000
    ).length;

    return {
      total: queue.length,
      lastHour,
      lastDay,
      oldest: queue[0]?.queuedAt || null,
      newest: queue[queue.length - 1]?.queuedAt || null,
    };
  } catch (error) {
    console.error('Error getting queue stats:', error);
    return { total: 0, lastHour: 0, lastDay: 0, oldest: null, newest: null };
  }
}

/**
 * Generate a unique ID for queue items
 * @returns {string} - Unique ID
 */
function generateId() {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

export default {
  initQueue,
  getQueue,
  enqueue,
  dequeue,
  clearQueue,
  getQueueStats,
};
