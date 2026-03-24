import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getSavedIds, savePrediction as apiSave, unsavePrediction as apiUnsave } from '../api';

const SavedPredictionsContext = createContext(null);

function getUserId() {
  let id = localStorage.getItem('qa_user_id');
  if (!id) {
    id = 'u_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem('qa_user_id', id);
  }
  return id;
}

export function SavedPredictionsProvider({ children }) {
  const [savedIds, setSavedIds] = useState(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem('qa_saved_predictions') || '[]'));
    } catch { return new Set(); }
  });
  const [toast, setToast] = useState(null);
  const userId = getUserId();

  // Sync with server on mount
  useEffect(() => {
    getSavedIds(userId).then(ids => {
      const merged = new Set([...savedIds, ...ids]);
      setSavedIds(merged);
      localStorage.setItem('qa_saved_predictions', JSON.stringify([...merged]));
    }).catch(() => {});
  }, []);

  // Persist to localStorage whenever savedIds changes
  useEffect(() => {
    localStorage.setItem('qa_saved_predictions', JSON.stringify([...savedIds]));
  }, [savedIds]);

  const showToast = useCallback((message, link) => {
    setToast({ message, link });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const isSaved = useCallback((predictionId) => {
    return savedIds.has(predictionId);
  }, [savedIds]);

  const toggleSave = useCallback(async (predictionId) => {
    const wasSaved = savedIds.has(predictionId);

    // Optimistic update
    setSavedIds(prev => {
      const next = new Set(prev);
      if (wasSaved) {
        next.delete(predictionId);
      } else {
        next.add(predictionId);
      }
      return next;
    });

    try {
      if (wasSaved) {
        await apiUnsave(userId, predictionId);
        showToast('Prediction removed from saved');
      } else {
        await apiSave(userId, predictionId);
        showToast('Prediction saved!', '/saved');
      }
    } catch {
      // Revert on failure
      setSavedIds(prev => {
        const next = new Set(prev);
        if (wasSaved) {
          next.add(predictionId);
        } else {
          next.delete(predictionId);
        }
        return next;
      });
    }
  }, [savedIds, userId, showToast]);

  const count = savedIds.size;

  return (
    <SavedPredictionsContext.Provider value={{ savedIds, isSaved, toggleSave, count, toast, userId }}>
      {children}
    </SavedPredictionsContext.Provider>
  );
}

export function useSavedPredictions() {
  const ctx = useContext(SavedPredictionsContext);
  if (!ctx) throw new Error('useSavedPredictions must be used within SavedPredictionsProvider');
  return ctx;
}
