import { useEffect, useState } from 'react';
import { getPredictionTemplates } from '../api';

const REASONING_PLACEHOLDERS = {
  custom: "Why do you think this will happen?",
  earnings_play: "What's your thesis going into earnings?",
  momentum_trade: "What trend or signal are you riding?",
  macro_thesis: "What's the fundamental case?",
  technical_breakout: "What level is it breaking through?",
  contrarian_bet: "Why is the crowd wrong?",
  sector_rotation: "Where is money flowing and why?",
};

/**
 * Props:
 *  - value: current template key
 *  - onChange(templateKey, templateData): called when template is selected
 */
export default function TemplateSelector({ value = 'custom', onChange }) {
  const [templates, setTemplates] = useState(null);

  useEffect(() => {
    getPredictionTemplates().then(setTemplates).catch(() => {});
  }, []);

  if (!templates) return null;

  const entries = Object.entries(templates);

  return (
    <div className="flex gap-2 overflow-x-auto pills-scroll pb-1">
      {entries.map(([key, tmpl]) => {
        const isActive = value === key;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key, tmpl)}
            className={`flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors border min-h-[40px] ${
              isActive
                ? 'bg-surface-2 text-text-primary'
                : 'bg-surface text-text-secondary border-border hover:border-accent/20'
            }`}
            style={isActive ? { borderColor: tmpl.color + '60', backgroundColor: tmpl.color + '10' } : {}}
          >
            <span>{tmpl.icon}</span>
            <span>{tmpl.name}</span>
          </button>
        );
      })}
    </div>
  );
}

export { REASONING_PLACEHOLDERS };
