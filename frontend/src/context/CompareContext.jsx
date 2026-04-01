import { createContext, useContext, useState, useCallback } from 'react';

const CompareContext = createContext(null);

export function CompareProvider({ children }) {
  const [tray, setTray] = useState([]); // [{id, name, firm, accuracy}]

  const addToCompare = useCallback((forecaster) => {
    setTray(prev => {
      if (prev.length >= 4) return prev;
      if (prev.some(f => f.id === forecaster.id)) return prev;
      return [...prev, { id: forecaster.id, name: forecaster.name, firm: forecaster.firm, accuracy: forecaster.accuracy_rate || forecaster.accuracy || 0 }];
    });
  }, []);

  const removeFromCompare = useCallback((id) => {
    setTray(prev => prev.filter(f => f.id !== id));
  }, []);

  const clearCompare = useCallback(() => setTray([]), []);

  const isInCompare = useCallback((id) => tray.some(f => f.id === id), [tray]);

  return (
    <CompareContext.Provider value={{ tray, addToCompare, removeFromCompare, clearCompare, isInCompare }}>
      {children}
    </CompareContext.Provider>
  );
}

export function useCompare() {
  return useContext(CompareContext);
}
