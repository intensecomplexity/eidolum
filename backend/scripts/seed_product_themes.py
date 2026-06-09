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
     "Smartphone makers and the chip suppliers behind every handset.",
     [("AAPL", True), ("CRUS", False), ("QCOM", False), ("QRVO", False),
      ("SWKS", False)]),
    ("ai-chips", "AI Chips",
     "The silicon powering the AI buildout — GPUs, accelerators, memory, and the foundry.",
     [("NVDA", True), ("AMD", True), ("AVGO", False), ("TSM", True),
      ("ARM", False), ("MRVL", False), ("MU", False), ("SMCI", False)]),
    ("ev", "EVs",
     "Electric vehicle makers, pure-play and legacy.",
     [("TSLA", True), ("RIVN", False), ("LCID", False), ("NIO", False),
      ("LI", False), ("GM", False), ("F", False)]),
    ("cloud", "Cloud",
     "Hyperscalers and the cloud-native infrastructure layer.",
     [("MSFT", True), ("AMZN", True), ("GOOGL", True), ("ORCL", False),
      ("SNOW", False), ("NET", False), ("DDOG", False)]),
    ("cybersecurity", "Cybersecurity",
     "Endpoint, network, and identity security platforms.",
     [("PANW", True), ("CRWD", True), ("ZS", False), ("FTNT", False),
      ("S", False), ("OKTA", False)]),
    ("streaming", "Streaming",
     "Video and audio streaming platforms fighting for screen time.",
     [("NFLX", True), ("DIS", True), ("WBD", False), ("SPOT", False),
      ("ROKU", False)]),
    ("ecommerce", "E-Commerce",
     "Online retail platforms and marketplaces.",
     [("AMZN", True), ("SHOP", True), ("MELI", False), ("ETSY", False),
      ("SE", False)]),
    ("social-media", "Social Media",
     "Ad-driven social platforms.",
     [("META", True), ("SNAP", False), ("PINS", False), ("RDDT", False)]),
    ("fintech-payments", "Fintech & Payments",
     "Payment rails, networks, and consumer fintech.",
     [("V", True), ("MA", True), ("PYPL", False), ("SQ", False),
      ("AXP", False)]),
    ("gaming", "Gaming",
     "Game publishers, platforms, and the hardware they run on.",
     [("EA", True), ("TTWO", True), ("RBLX", False), ("U", False)]),
    ("semiconductors-equip", "Chip Equipment",
     "The toolmakers every fab depends on — lithography, deposition, etch, test.",
     [("ASML", True), ("AMAT", True), ("LRCX", False), ("KLAC", False)]),
    ("clean-energy", "Solar",
     "Solar, storage, and residential energy.",
     [("ENPH", True), ("FSLR", True), ("SEDG", False), ("RUN", False)]),
    ("space", "Space",
     "Launch, lunar, and aerospace-defense exposure to the space economy.",
     [("RKLB", True), ("LUNR", False), ("BA", False), ("LMT", False)]),
    ("weight-loss-glp1", "Weight Loss (GLP-1)",
     "The GLP-1 obesity-drug wave and its challengers.",
     [("LLY", True), ("NVO", True), ("VKTX", False)]),
    ("robotics-automation", "Robotics & Automation",
     "Industrial automation, surgical robotics, and test systems.",
     [("ISRG", True), ("ABB", False), ("ROK", False), ("TER", False)]),
    ("ride-delivery", "Ride & Delivery",
     "Ride-hailing and on-demand delivery networks.",
     [("UBER", True), ("LYFT", False), ("DASH", False), ("GRAB", False)]),
    ("crypto-equities", "Crypto Equities",
     "Exchanges, miners, and balance-sheet bitcoin proxies.",
     [("COIN", True), ("MSTR", True), ("MARA", False), ("RIOT", False),
      ("HOOD", False)]),
    ("ad-tech", "Ad Tech",
     "The programmatic advertising stack and the walled gardens.",
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
    # DO UPDATE on name (only) so a re-run reconciles display renames
    # ("Clean Energy" → "Solar") instead of silently keeping stale text.
    # Membership stays DO NOTHING — the script never deletes, so admin
    # removals survive as long as this seed list mirrors prod.
    execute_values(cur, """
        INSERT INTO themes (slug, name, description, display_order)
        VALUES %s
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
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
