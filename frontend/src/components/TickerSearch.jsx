import { useState, useEffect, useRef } from 'react';
import { Search, Check } from 'lucide-react';
import { searchTickers } from '../api';

/**
 * Reusable ticker autocomplete search input.
 *
 * Props:
 *  - value: string — current selected ticker (e.g. "TSLA")
 *  - onChange(ticker, name): called when a ticker is confirmed
 *  - placeholder: string
 *  - className: string — wrapper classes
 *  - inputClassName: string — input classes
 *  - autoFocus: boolean
 */
export default function TickerSearch({
  value = '',
  onChange,
  placeholder = 'Search ticker or company...',
  className = '',
  inputClassName = '',
  autoFocus = false,
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [selectedTicker, setSelectedTicker] = useState(value || '');
  const [selectedName, setSelectedName] = useState('');
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);
  const latestResults = useRef([]);

  // Keep a ref to results so keyboard handler always has the latest
  latestResults.current = results;

  // Close on click outside
  useEffect(() => {
    function handle(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handle);
    document.addEventListener('touchstart', handle);
    return () => {
      document.removeEventListener('mousedown', handle);
      document.removeEventListener('touchstart', handle);
    };
  }, []);

  // Close on Escape
  useEffect(() => {
    function handle(e) { if (e.key === 'Escape') setOpen(false); }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);

  // Sync if parent resets value to ''
  useEffect(() => {
    if (!value && selectedTicker) {
      setSelectedTicker('');
      setSelectedName('');
      setQuery('');
    }
  }, [value]);

  function doSearch(text) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(() => {
      searchTickers(text.trim())
        .then(r => {
          setResults(r);
          setHighlightIdx(r.length > 0 ? 0 : -1);
          setOpen(r.length > 0);
        })
        .catch(() => { setResults([]); setOpen(false); });
    }, 300);
  }

  function handleInput(text) {
    setQuery(text);
    setSelectedTicker('');
    setSelectedName('');
    doSearch(text);
  }

  function confirmSelection(item) {
    setSelectedTicker(item.ticker);
    setSelectedName(item.name);
    setQuery('');
    setOpen(false);
    setResults([]);
    setHighlightIdx(-1);
    if (onChange) onChange(item.ticker, item.name);
  }

  function handleKeyDown(e) {
    if (!open || latestResults.current.length === 0) {
      // If user presses Enter with typed text and NO dropdown, try to auto-resolve
      if (e.key === 'Enter' && query.trim() && !selectedTicker) {
        e.preventDefault();
        // Fire a synchronous search and select first result
        searchTickers(query.trim())
          .then(r => {
            if (r.length > 0) confirmSelection(r[0]);
          })
          .catch(() => {});
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx(i => Math.min(i + 1, latestResults.current.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const idx = highlightIdx >= 0 ? highlightIdx : 0;
      if (latestResults.current[idx]) {
        confirmSelection(latestResults.current[idx]);
      }
    }
  }

  // What to show in the input field
  const displayValue = selectedTicker
    ? (selectedName ? `${selectedTicker} - ${selectedName}` : selectedTicker)
    : query;

  return (
    <div className={`relative ${className}`} ref={wrapperRef}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input
          type="text"
          value={displayValue}
          onChange={e => {
            if (selectedTicker) {
              // User is editing after a selection — clear and start fresh
              setSelectedTicker('');
              setSelectedName('');
              const cleaned = e.target.value
                .replace(`${selectedTicker} - ${selectedName}`, '')
                .replace(selectedTicker, '')
                .trim();
              handleInput(cleaned || e.target.value);
            } else {
              handleInput(e.target.value);
            }
          }}
          onFocus={() => { if (results.length > 0 && !selectedTicker) setOpen(true); }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className={`w-full pl-9 pr-10 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono text-lg tracking-wider ${inputClassName}`}
        />
        {!!selectedTicker && (
          <Check className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-positive" />
        )}
      </div>

      {/* Dropdown */}
      {open && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-surface border border-border rounded-lg shadow-lg overflow-hidden">
          {results.map((item, idx) => (
            <button
              key={item.ticker}
              type="button"
              onClick={() => confirmSelection(item)}
              className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors border-b border-border last:border-b-0 ${
                idx === highlightIdx ? 'bg-surface-2' : 'hover:bg-surface-2 active:bg-surface-2'
              }`}
            >
              <span className="font-mono font-bold text-accent text-sm tracking-wider min-w-[48px]">
                {item.ticker}
              </span>
              <span className="text-text-secondary text-sm truncate">
                {item.name}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
