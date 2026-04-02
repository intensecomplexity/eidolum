import { useEffect } from 'react';

/**
 * Set page title, meta description, and Open Graph tags.
 * @param {{ title?: string, description?: string, url?: string }} opts
 */
export default function useSEO({ title, description, url } = {}) {
  useEffect(() => {
    if (title) {
      document.title = title;
      setMeta('og:title', title);
      setMeta('twitter:title', title);
    }
    if (description) {
      setMeta('description', description);
      setMeta('og:description', description);
      setMeta('twitter:description', description);
    }
    if (url) {
      setMeta('og:url', url);
    }
    setMeta('og:type', 'website');
    setMeta('og:site_name', 'Eidolum');
    setMeta('twitter:card', 'summary');
  }, [title, description, url]);
}

function setMeta(name, content) {
  const attr = name.startsWith('og:') || name.startsWith('twitter:') ? 'property' : 'name';
  let tag = document.querySelector(`meta[${attr}="${name}"]`);
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute(attr, name);
    document.head.appendChild(tag);
  }
  tag.setAttribute('content', content);
}
