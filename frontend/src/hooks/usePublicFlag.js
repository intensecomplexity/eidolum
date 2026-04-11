import { useEffect, useState } from 'react';
import { getPublicFlags } from '../api';

// Ship #13. Reads the allow-listed public feature flags and returns the
// value for `key`. Never blocks render: starts at `defaultValue`, swaps
// in the real value once the fetch resolves. Failures keep the default.
export function usePublicFlag(key, defaultValue = false) {
  const [value, setValue] = useState(defaultValue);
  useEffect(() => {
    let active = true;
    getPublicFlags()
      .then(flags => {
        if (!active) return;
        if (flags && typeof flags[key] === 'boolean') setValue(flags[key]);
      })
      .catch(() => {});
    return () => { active = false; };
  }, [key]);
  return value;
}
