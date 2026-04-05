import { useEffect } from 'react';

const JSONLD_ID = 'eidolum-jsonld';

/**
 * Set page title, meta description, Open Graph, Twitter card tags,
 * and optional JSON-LD structured data.
 *
 * @param {{ title?: string, description?: string, url?: string, image?: string, jsonLd?: object|object[] }} opts
 */
export default function useSEO({ title, description, url, image, jsonLd } = {}) {
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
    if (image) {
      setMeta('og:image', image);
      setMeta('twitter:image', image);
      setMeta('twitter:card', 'summary_large_image');
    } else {
      setMeta('twitter:card', 'summary');
    }
    setMeta('og:type', 'website');
    setMeta('og:site_name', 'Eidolum \u2014 Analyst Accuracy Scored by Reality');

    // JSON-LD structured data
    if (jsonLd) {
      let el = document.getElementById(JSONLD_ID);
      if (!el) {
        el = document.createElement('script');
        el.id = JSONLD_ID;
        el.type = 'application/ld+json';
        document.head.appendChild(el);
      }
      el.textContent = JSON.stringify(jsonLd);
    }

    return () => {
      // Clean up JSON-LD on unmount so pages don't inherit stale data
      const el = document.getElementById(JSONLD_ID);
      if (el) el.remove();
    };
  }, [title, description, url, image, jsonLd]);
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
