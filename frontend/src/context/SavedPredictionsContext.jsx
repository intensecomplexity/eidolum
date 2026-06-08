import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getSavedIds, savePrediction as apiSave, unsavePrediction as apiUnsave } from '../api';
import { useLimitReached, getLimitReachedMessage } from './LimitReachedContext';

const SavedPredictionsContext = createContext(null);

export function SavedPredictionsProvider({ children }) {
  const [savedIds, setSavedIds] = useState(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem('qa_saved_predictions') || '[]'));
    } catch { return new Set(); }
  });
  const [toast, setToast] = useState(null);
  const { show: showLimitReached } = useLimitReached();

  // Sync with server on mount (scoped to the authenticated user via JWT)
  useEffect(() => {
    getSavedIds().then(ids => {
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
        await apiUnsave(predictionId);
        showToast('Prediction removed from saved');
      } else {
        await apiSave(predictionId);
        showToast('Prediction saved!', '/saved');
      }
    } catch (err) {
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
      const limitMsg = getLimitReachedMessage(err);
      if (limitMsg) {
        showLimitReached(limitMsg);
      }
    }
  }, [savedIds, showToast, showLimitReached]);

  const count = savedIds.size;

  return (
    <SavedPredictionsContext.Provider value={{ savedIds, isSaved, toggleSave, count, toast }}>
      {children}
    </SavedPredictionsContext.Provider>
  );
}

export function useSavedPredictions() {
  const ctx = useContext(SavedPredictionsContext);
  if (!ctx) throw new Error('useSavedPredictions must be used within SavedPredictionsProvider');
  return ctx;
}
