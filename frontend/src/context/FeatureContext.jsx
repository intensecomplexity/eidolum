import { createContext, useContext, useEffect, useState } from 'react';
import { getFeatureFlags } from '../api';

const FeatureContext = createContext({
  tournaments: false, daily_challenge: false, duels: false, compete: false, compare_analysts: false, loaded: false,
});

export function FeatureProvider({ children }) {
  const [flags, setFlags] = useState({
    tournaments: false, daily_challenge: false, duels: false, compete: false, compare_analysts: false, loaded: false,
  });

  useEffect(() => {
    getFeatureFlags()
      .then(f => setFlags({ ...f, loaded: true }))
      .catch(() => setFlags(prev => ({ ...prev, loaded: true })));
  }, []);

  return <FeatureContext.Provider value={flags}>{children}</FeatureContext.Provider>;
}

export function useFeatures() {
  return useContext(FeatureContext);
}
