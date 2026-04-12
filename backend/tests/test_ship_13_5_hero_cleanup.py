"""Ship #13.5 — homepage hero cleanup invariants.

Source-level smoke assertions for the cleanup ship. The frontend has no
jsx/vitest runner in the local venv, so we validate the ship the same
way Ship #13 and Ship #14 did: by reading source files and asserting
the contracts the spec promises. Run with:

    cd backend
    venv/bin/python -m unittest tests.test_ship_13_5_hero_cleanup -v

Coverage:
  * HeroBand hero content — manifesto line, three stat tiles pulled
    from /api/stats/global, Instrument Serif via `headline-serif` on
    the big numbers, and the tightened bottom padding that closes the
    hero→Receipts gap.
  * SectionHeader component renders a gold <hr> (border-t border-accent)
    and uses max-contrast label color, 0.08em tracking.
  * Receipts header — Dashboard wraps the Biggest Calls block with
    <SectionHeader> and flips its label to "Receipts" when the hero
    flag is on, with the correct subtitle.
  * Badge glow — PredictionBadge box-shadow rgba strings match the
    spec's exact values (green-500 / yellow-500 / red-500 at 35%).
  * First-call CTA — Dashboard flips scored_predictions === 0 + flag
    on to the CTA tile with headline-serif copy; otherwise it falls
    back to the personal stats card.
  * Footer manifesto — `headline-serif italic text-base text-accent`,
    no more Sora sans.
  * tnum — explicit `.tnum` utility lives in index.css and is applied
    to leaderboard accuracy / avg return / sector / hero stat tiles.
  * HAIKU_SYSTEM + classifier files are byte-identical vs git HEAD.
"""

import hashlib
import os
import subprocess
import unittest


HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FRONTEND = os.path.join(REPO, "frontend", "src")
BACKEND = os.path.join(REPO, "backend")


def _read_frontend(rel):
    with open(os.path.join(FRONTEND, rel), "r", encoding="utf-8") as f:
        return f.read()


def _read_repo(rel):
    with open(os.path.join(REPO, rel), "r", encoding="utf-8") as f:
        return f.read()


def _sha256_path(rel):
    with open(os.path.join(REPO, rel), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _git_blob_sha256(rel):
    try:
        out = subprocess.run(
            ["git", "-C", REPO, "show", f"HEAD:{rel}"],
            capture_output=True,
            check=True,
        )
        return hashlib.sha256(out.stdout).hexdigest()
    except subprocess.CalledProcessError:
        return None


class HeroBandTests(unittest.TestCase):
    """Spec: manifesto + stat tiles + tightened padding."""

    def setUp(self):
        self.src = _read_frontend("components/home/HeroBand.jsx")

    def test_manifesto_line_present_with_headline_serif(self):
        self.assertIn("Truth is the only currency.", self.src)
        # Must be Instrument Serif (headline-serif class) + italic +
        # accent gold + at least text-base on mobile / text-xl desktop.
        self.assertRegex(
            self.src,
            r"headline-serif[^\"]*italic[^\"]*text-accent[^\"]*text-base[^\"]*sm:text-xl"
            r"|headline-serif[^\"]*italic[^\"]*text-base[^\"]*sm:text-xl[^\"]*text-accent",
        )

    def test_three_stat_tiles_pulled_from_stats_endpoint(self):
        # Numbers come from getGlobalStats() -> total_predictions /
        # total_forecasters / total_scored. No hardcoded 274,000+ etc.
        self.assertIn("getGlobalStats", self.src)
        self.assertIn("total_predictions", self.src)
        self.assertIn("total_forecasters", self.src)
        self.assertIn("total_scored", self.src)
        # The three tile labels the spec requires.
        self.assertIn("Predictions Tracked", self.src)
        self.assertIn("Forecasters Watched", self.src)
        self.assertIn("Calls Graded", self.src)
        # No hardcoded k-suffixed numbers in the source.
        self.assertNotIn("274,000", self.src)
        self.assertNotIn("6,000+", self.src)
        self.assertNotIn("31,000", self.src)

    def test_stat_tile_uses_headline_serif_and_tnum(self):
        # Big numbers must use headline-serif (Instrument Serif) and
        # the new .tnum utility so the digits align column-wise.
        self.assertRegex(
            self.src,
            r"headline-serif\s+tnum[^\"]*text-4xl",
            msg="stat tile numbers must be headline-serif tnum text-4xl",
        )

    def test_hero_bottom_padding_tightened(self):
        # Ship #13 had py-10 sm:py-16 (symmetrical). Ship #13.5 splits
        # to pt-10/16 top + pb-8/12 bottom so the hero's bottom edge
        # sits closer to the Receipts section header below.
        self.assertIn("pt-10 sm:pt-16 pb-8 sm:pb-12", self.src)


class SectionHeaderTests(unittest.TestCase):
    def setUp(self):
        self.src = _read_frontend("components/SectionHeader.jsx")

    def test_renders_gold_hr_and_max_contrast_label(self):
        # 1px gold rule via Tailwind `border-accent` token — not a
        # hardcoded hex. Aria-hidden so it's decorative.
        self.assertIn('border-t border-accent', self.src)
        self.assertIn('aria-hidden="true"', self.src)
        # Label color = text-text-primary (flips to near-black in
        # light mode, near-white in dark mode via the theme override).
        self.assertIn('text-text-primary', self.src)
        # 0.08em tracking per spec.
        self.assertIn("letterSpacing: '0.08em'", self.src)

    def test_subtitle_prop_optional(self):
        # When subtitle is undefined the <p> element is not rendered.
        self.assertIn("{subtitle &&", self.src)

    def test_default_tag_is_h2(self):
        self.assertRegex(self.src, r"as:\s*Tag\s*=\s*'h2'")


class DashboardWiringTests(unittest.TestCase):
    def setUp(self):
        self.src = _read_frontend("pages/Dashboard.jsx")

    def test_receipts_header_flag_gated(self):
        # With the flag on, the block renders <SectionHeader>Receipts</>
        # with the exact subtitle; with the flag off it falls back to
        # the Biggest Calls label (also via SectionHeader for the
        # unconditional gold rule upgrade).
        self.assertIn("import SectionHeader", self.src)
        self.assertIn("Receipts", self.src)
        self.assertIn("Biggest Calls", self.src)
        self.assertIn(
            "Recently graded — locked when made, settled by reality.",
            self.src,
        )
        # The Receipts header is only rendered when heroEnabled is true.
        self.assertRegex(
            self.src,
            r"heroEnabled\s*\?\s*\(\s*\n\s*<SectionHeader subtitle=[^>]*>\s*\n\s*Receipts",
        )

    def test_first_call_cta_gated_on_scored_count_zero(self):
        # `showFirstCallCta = heroEnabled && isFirstCall`, where
        # isFirstCall is true iff profile.scored_predictions === 0.
        self.assertIn("showFirstCallCta", self.src)
        self.assertIn("scored_predictions", self.src)
        # The CTA copy and its Instrument Serif headline.
        self.assertIn("Make your first call", self.src)
        self.assertIn(
            "Pick a ticker, set a target, lock it. The market will grade you.",
            self.src,
        )
        self.assertRegex(
            self.src,
            r"headline-serif[^\"]*text-2xl[^\"]*sm:text-3xl",
        )

    def test_personal_stats_hidden_when_cta_shows(self):
        # The existing personal stats card must NOT render alongside
        # the CTA tile — the CTA replaces it.
        self.assertIn(
            "profile && !showFirstCallCta",
            self.src,
            msg="personal stats card must be hidden when the first-call CTA is showing",
        )

    def test_receipts_block_has_mt0_when_flag_on(self):
        # Step 9 — reduce the receipt section's top margin to 0 when
        # the hero is rendered above, so the hero's pb handles spacing
        # without a visible blank zone.
        self.assertRegex(
            self.src,
            r"heroEnabled\s*\?\s*'mt-0 mb-6'",
        )


class PredictionBadgeGlowTests(unittest.TestCase):
    def setUp(self):
        self.src = _read_frontend("components/PredictionBadge.jsx")

    def test_glow_rgba_matches_spec(self):
        # Spec values — green-500 / yellow-500 / red-500 at 35% alpha.
        self.assertIn("0 0 12px rgba(34, 197, 94, 0.35)", self.src)
        self.assertIn("0 0 12px rgba(234, 179, 8, 0.35)", self.src)
        self.assertIn("0 0 12px rgba(239, 68, 68, 0.35)", self.src)


class FooterTypographyTests(unittest.TestCase):
    def setUp(self):
        self.src = _read_frontend("components/Footer.jsx")

    def test_manifesto_uses_headline_serif_italic_gold(self):
        self.assertIn("Truth is the only currency.", self.src)
        # Must be the Instrument Serif `headline-serif` class, italic,
        # text-base (=16px), and text-accent (gold). And must NOT be
        # the old `italic text-sm text-accent` Sora combo.
        self.assertRegex(
            self.src,
            r'className="headline-serif italic text-base text-accent"',
        )


class TnumUtilityTests(unittest.TestCase):
    def test_tnum_class_declared_in_css(self):
        css = _read_repo("frontend/src/index.css")
        self.assertIn(".tnum", css)
        # Two declarations in the block — font-variant-numeric and
        # font-feature-settings.
        self.assertRegex(
            css,
            r"\.tnum\s*\{[^}]*font-variant-numeric:\s*tabular-nums[^}]*font-feature-settings:\s*\"tnum\"\s*1",
        )

    def test_leaderboard_accuracy_column_has_tnum(self):
        src = _read_frontend("pages/Leaderboard.jsx")
        # The accuracy-rate span in the main table picks up tnum.
        self.assertIn("font-mono tnum font-medium", src)
        # At least four numeric spans must carry tnum — accuracy,
        # metric, sector call, pair call.
        count = src.count("tnum")
        self.assertGreaterEqual(count, 8, f"expected >=8 tnum sites, got {count}")

    def test_hero_stat_tiles_have_tnum(self):
        src = _read_frontend("components/home/HeroBand.jsx")
        self.assertIn("headline-serif tnum", src)

    def test_dashboard_numeric_cells_have_tnum(self):
        src = _read_frontend("pages/Dashboard.jsx")
        # StatusItem value, Lv.N pill, top analysts accuracy, avg
        # return, scored count, receipts return %, expiring pnl %.
        count = src.count("tnum")
        self.assertGreaterEqual(count, 7, f"expected >=7 tnum sites, got {count}")


class HaikuByteIdenticalTests(unittest.TestCase):
    """Constraint #1 — HAIKU_SYSTEM and the 14 blocks must be byte-
    identical vs git HEAD. Ship #13.5 is frontend-only."""

    FILES = [
        "backend/jobs/youtube_classifier.py",
        "backend/jobs/x_scraper.py",
    ]

    def test_classifiers_match_head(self):
        for rel in self.FILES:
            head = _git_blob_sha256(rel)
            self.assertIsNotNone(head, f"could not read HEAD blob for {rel}")
            disk = _sha256_path(rel)
            self.assertEqual(
                head,
                disk,
                f"{rel} must be byte-identical vs git HEAD (Ship #13.5 is frontend-only)",
            )


if __name__ == "__main__":
    unittest.main()
