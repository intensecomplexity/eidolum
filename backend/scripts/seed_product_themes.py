"""
seed_product_themes.py — seed the Product Themes v1 starter set.

18 hand-curated themes, US-listed tickers first (that's where prediction
coverage lives). Rosters mirror the CURATED prod state (2026-06-09 review:
phones/gaming/glp1/fintech/ev trims, clean-energy renamed "Solar") so a
re-run is a no-op, not a regression. Idempotent: themes upsert reconciles
name on conflict; memberships are ON CONFLICT DO NOTHING and the script
never deletes — KEEP THIS LIST IN SYNC with admin removals, or a re-run
silently re-adds removed tickers. Also ensures the ENABLE_PRODUCT_THEMES
config row exists (value 'false') so the flip is a single UPDATE.

Run locally against the Railway DB:
    DATABASE_PUBLIC_URL=postgres://... python backend/scripts/seed_product_themes.py
"""
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

# (slug, name, description, [(ticker, is_primary), ...])
THEMES = [
    ("phones", "Phones",
     "Smartphone makers and the chip and component suppliers inside the handset.",
     [("AAPL", True), ("CRUS", False), ("QCOM", False), ("QRVO", False),
      ("SWKS", False)]),
    ("ai-chips", "AI Chips",
     "Designers and makers of the GPUs and accelerators powering AI workloads.",
     [("NVDA", True), ("AMD", True), ("AVGO", False), ("TSM", True),
      ("ARM", False), ("MRVL", False), ("MU", False), ("SMCI", False)]),
    ("ev", "EVs",
     "Electric-vehicle makers and the pure-play challengers to legacy autos.",
     [("TSLA", True), ("RIVN", False), ("LCID", False), ("NIO", False),
      ("LI", False), ("GM", False), ("F", False)]),
    ("cloud", "Cloud",
     "Hyperscale platforms and the software running infrastructure in the cloud.",
     [("MSFT", True), ("AMZN", True), ("GOOGL", True), ("ORCL", False),
      ("SNOW", False), ("NET", False), ("DDOG", False)]),
    ("cybersecurity", "Cybersecurity",
     "Companies defending networks, endpoints, and identity from attack.",
     [("PANW", True), ("CRWD", True), ("ZS", False), ("FTNT", False),
      ("S", False), ("OKTA", False)]),
    ("streaming", "Streaming",
     "Video and audio streaming platforms competing for subscriber time.",
     [("NFLX", True), ("DIS", True), ("WBD", False), ("SPOT", False),
      ("ROKU", False)]),
    ("ecommerce", "E-Commerce",
     "Online marketplaces and the platforms powering digital retail.",
     [("AMZN", True), ("SHOP", True), ("MELI", False), ("ETSY", False),
      ("SE", False)]),
    ("social-media", "Social Media",
     "Platforms built on user-generated content and the attention economy.",
     [("META", True), ("SNAP", False), ("PINS", False), ("RDDT", False)]),
    ("fintech-payments", "Fintech & Payments",
     "Card networks, processors, and the digital-payment disruptors.",
     [("V", True), ("MA", True), ("PYPL", False), ("SQ", False),
      ("AXP", False)]),
    ("gaming", "Gaming",
     "Video-game publishers and interactive-entertainment platforms.",
     [("EA", True), ("TTWO", True), ("RBLX", False), ("U", False)]),
    ("semiconductors-equip", "Chip Equipment",
     "The toolmakers that build chip-fabrication lines.",
     [("ASML", True), ("AMAT", True), ("LRCX", False), ("KLAC", False)]),
    ("clean-energy", "Solar",
     "Solar manufacturers, inverters, and residential installers.",
     [("ENPH", True), ("FSLR", True), ("SEDG", False), ("RUN", False)]),
    ("space", "Space",
     "Launch providers and the aerospace names reaching orbit.",
     [("RKLB", True), ("LUNR", False), ("BA", False), ("LMT", False)]),
    ("weight-loss-glp1", "Weight Loss (GLP-1)",
     "Drugmakers behind GLP-1 obesity and diabetes treatments.",
     [("LLY", True), ("NVO", True), ("VKTX", False)]),
    ("robotics-automation", "Robotics & Automation",
     "Industrial robotics, factory automation, and surgical-robot makers.",
     [("ISRG", True), ("ABB", False), ("ROK", False), ("TER", False)]),
    ("ride-delivery", "Ride & Delivery",
     "Rideshare and on-demand delivery platforms.",
     [("UBER", True), ("LYFT", False), ("DASH", False), ("GRAB", False)]),
    ("crypto-equities", "Crypto Equities",
     "Public stocks levered to crypto — exchanges, miners, and holders.",
     [("COIN", True), ("MSTR", True), ("MARA", False), ("RIOT", False),
      ("HOOD", False)]),
    ("ad-tech", "Ad Tech",
     "The platforms and exchanges that buy, sell, and target digital ads.",
     [("TTD", True), ("GOOGL", False), ("META", False), ("APP", False),
      ("PUBM", False)]),
]


def main():
    dsn = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: set DATABASE_PUBLIC_URL (or DATABASE_URL)")
        sys.exit(1)

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()

    theme_rows = [
        (slug, name, desc, (i + 1) * 10)
        for i, (slug, name, desc, _members) in enumerate(THEMES)
    ]
    # DO UPDATE on name + description so a re-run reconciles display
    # copy (renames, explainer text) instead of silently keeping stale text.
    # Membership stays DO NOTHING — the script never deletes, so admin
    # removals survive as long as this seed list mirrors prod.
    execute_values(cur, """
        INSERT INTO themes (slug, name, description, display_order)
        VALUES %s
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name,
                                 description = EXCLUDED.description
    """, theme_rows)

    cur.execute("SELECT id, slug FROM themes")
    id_by_slug = {slug: tid for tid, slug in cur.fetchall()}

    member_rows = []
    for slug, _name, _desc, members in THEMES:
        tid = id_by_slug.get(slug)
        if tid is None:
            print(f"WARN: theme {slug} missing after insert — skipped")
            continue
        for ticker, is_primary in members:
            member_rows.append((tid, ticker, is_primary))
    execute_values(cur, """
        INSERT INTO theme_tickers (theme_id, ticker, is_primary)
        VALUES %s
        ON CONFLICT (theme_id, ticker) DO NOTHING
    """, member_rows)

    # Make the flag row exist (default OFF) so flipping it on is a
    # single UPDATE, never an INSERT-or-UPDATE dance.
    cur.execute("""
        INSERT INTO config (key, value) VALUES ('ENABLE_PRODUCT_THEMES', 'false')
        ON CONFLICT (key) DO NOTHING
    """)

    conn.commit()

    cur.execute("""
        SELECT t.slug, t.name, COUNT(tt.ticker) AS n,
               COUNT(*) FILTER (WHERE tt.is_primary) AS n_primary
        FROM themes t
        LEFT JOIN theme_tickers tt ON tt.theme_id = t.id
        GROUP BY t.slug, t.name, t.display_order
        ORDER BY t.display_order
    """)
    print(f"{'slug':<22} {'name':<24} tickers  primary")
    total = 0
    for slug, name, n, n_primary in cur.fetchall():
        print(f"{slug:<22} {name:<24} {n:>7}  {n_primary:>7}")
        total += n
    print(f"\n{len(id_by_slug)} themes, {total} membership rows total")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
