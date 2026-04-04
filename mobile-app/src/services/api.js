import AsyncStorage from '@react-native-async-storage/async-storage';

// Cloud relay API base URL
const API_BASE_URL = 'http://localhost:8000/api';

// Queue key for AsyncStorage
const QUEUE_KEY = '@worklog_queue';

/**
 * Upload a work log to the cloud relay server
 * @param {Object} workLog - The work log data to upload
 * @returns {Promise<Object>} - The server response
 */
export async function uploadWorkLog(workLog) {
  try {
    const response = await fetch(`${API_BASE_URL}/upload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        type: 'work_log',
        data: workLog,
      }),
    });

    if (!response.ok) {
      throw new Error(`Server responded with status: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error('Upload failed:', error);
    throw error;
  }
}

/**
 * Get all queued work logs pending upload
 * @returns {Promise<Array>} - Array of queued work logs
 */
export async function getQueuedWorkLogs() {
  try {
    const queued = await AsyncStorage.getItem(QUEUE_KEY);
    return queued ? JSON.parse(queued) : [];
  } catch (error) {
    console.error('Error getting queued work logs:', error);
    return [];
  }
}

/**
 * Sync queued work logs to the server
 * Attempts to upload all queued items and removes successful ones
 * @returns {Promise<Object>} - Result with success/failure counts
 */
export async function syncQueuedWorkLogs() {
  const queue = await getQueuedWorkLogs();
  const failed = [];
  let successCount = 0;

  for (const item of queue) {
    try {
      await uploadWorkLog(item);
      successCount++;
    } catch (error) {
      console.error('Failed to sync queued item:', error);
      failed.push(item);
    }
  }

  // Save failed items back to queue
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(failed));

  return {
    success: successCount,
    failed: failed.length,
  };
}

/**
 * Add a work log to the upload queue
 * @param {Object} workLog - The work log data to queue
 * @returns {Promise<void>}
 */
export async function queueWorkLog(workLog) {
  try {
    const queue = await getQueuedWorkLogs();
    queue.push({
      ...workLog,
      queuedAt: new Date().toISOString(),
    });
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  } catch (error) {
    console.error('Error queuing work log:', error);
    throw error;
  }
}

export default {
  uploadWorkLog,
  getQueuedWorkLogs,
  syncQueuedWorkLogs,
  queueWorkLog,
};
