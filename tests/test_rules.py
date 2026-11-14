import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mf import rules  # noqa: E402
from mf.util import Refused  # noqa: E402

TARGETS = ["ios", "android"]
ROUTING = {
    "code": {"low": "haiku", "medium": "sonnet", "high": "sonnet"},
    "parity": "sonnet",
    "surfaces": {"ui": {"ui": "haiku", "a11y": "sonnet"}, "security": {"security": "opus"}, "native": {}},
}


class Header(unittest.TestCase):
    def test_reads_until_blank_line(self):
        text = "DECISION: ACCEPT\nRISK: low\n\n## Summary\nKEY: not header\n"
        self.assertEqual(rules.header(text), {"DECISION": "ACCEPT", "RISK": "low"})

    def test_stops_at_a_heading(self):
        self.assertEqual(rules.header("# Title: with colon\nX: y"), {})

    def test_body_and_section(self):
        text = "STATUS: BLOCKED\nROUND: 1\n\n## Summary\n- a\n\n## Blocked\nNo simulator.\n"
        self.assertTrue(rules.body(text).startswith("## Summary"))
        self.assertEqual(rules.section(text, "Blocked"), "No simulator.")
        self.assertIsNone(rules.section(text, "Missing"))


class Intake(unittest.TestCase):
    def parse(self, **fields):
        base = {"DECISION": "ACCEPT", "PLATFORMS": "ios, android", "RISK": "low",
                "SURFACES": "none", "RESCOPED": "no"}
        base.update(fields)
        return rules.parse_intake("\n".join(f"{k}: {v}" for k, v in base.items()) + "\n\n## Summary\n", TARGETS)

    def test_both_expands(self):
        self.assertEqual(self.parse(PLATFORMS="both")["platforms"], TARGETS)

    def test_order_follows_config(self):
        self.assertEqual(self.parse(PLATFORMS="android, ios")["platforms"], TARGETS)

    def test_unknown_platform(self):
        with self.assertRaises(Refused):
            self.parse(PLATFORMS="windows")

    def test_accept_needs_platforms(self):
        with self.assertRaises(Refused):
            self.parse(PLATFORMS="none")

    def test_reject_may_skip_platforms(self):
        self.assertEqual(self.parse(DECISION="REJECT", PLATFORMS="none")["platforms"], [])

    def test_bad_surface(self):
        with self.assertRaises(Refused):
            self.parse(SURFACES="ui, money")

    def test_bad_decision(self):
        with self.assertRaises(Refused):
            self.parse(DECISION="MAYBE")


class Route(unittest.TestCase):
    def test_single_platform_low_risk(self):
        r = rules.route({"platforms": ["ios"], "risk": "low", "surfaces": []}, ROUTING)
        self.assertEqual(r, {"code-ios": "haiku"})

    def test_both_platforms_get_parity_and_surfaces(self):
        r = rules.route({"platforms": TARGETS, "risk": "medium", "surfaces": ["ui", "security", "native"]},
                        ROUTING)
        self.assertEqual(r, {"code-ios": "sonnet", "code-android": "sonnet", "parity": "sonnet",
                             "ui": "haiku", "a11y": "sonnet", "security": "opus"})


class Reviews(unittest.TestCase):
    def test_changes_must_name_targets(self):
        with self.assertRaises(Refused):
            rules.parse_review("VERDICT: CHANGES\nTARGETS: none\n", TARGETS)

    def test_target_outside_job(self):
        with self.assertRaises(Refused):
            rules.parse_review("VERDICT: CHANGES\nTARGETS: android\n", ["ios"])

    def test_rebuild_union(self):
        parsed = {
            "code-ios": ("PASS", []),
            "parity": ("CHANGES", ["android"]),
            "a11y": ("CHANGES", ["ios", "android"]),
        }
        self.assertEqual(rules.rebuild_targets(parsed), ["android", "ios"])

    def test_all_pass(self):
        self.assertEqual(rules.rebuild_targets({"x": ("PASS", [])}), [])


class Moves(unittest.TestCase):
    def test_illegal_job_move(self):
        with self.assertRaises(Refused):
            rules.check_move(rules.JOB_MOVES, "job", "intake", "build")

    def test_merged_from_anywhere_not_done(self):
        rules.check_move(rules.JOB_MOVES, "job", "review", "merged")
        with self.assertRaises(Refused):
            rules.check_move(rules.JOB_MOVES, "job", "rejected", "merged")

    def test_track_cannot_skip_gate(self):
        with self.assertRaises(Refused):
            rules.check_move(rules.TRACK_MOVES, "t", "build", "passed")

    def test_settle(self):
        self.assertEqual(rules.settle({"ios": "passed", "android": "gate"}), "build")
        self.assertEqual(rules.settle({"ios": "passed", "android": "blocked"}), "needs-human")
        self.assertEqual(rules.settle({"ios": "blocked", "android": "build"}), "build")
        self.assertEqual(rules.settle({"ios": "passed", "android": "passed"}), "review")

    def test_slug(self):
        self.assertEqual(rules.slug("Add Dark-mode toggle to Settings screen now"), "add-dark-mode-toggle-to")


class Survey(unittest.TestCase):
    SUGGESTIONS = (
        "# Suggestions\n\nIntro text is ignored.\n\n"
        "## Suggestion: Add pull-to-refresh to the iOS feed\n"
        "KIND: parity\nPLATFORMS: ios\nRISK: low\n\n"
        "Android refreshes the feed with a swipe (FeedScreen.kt); iOS can't.\n\n"
        "## Suggestion: Convert to synchronized folders\n"
        "KIND: factory\nPLATFORMS: ios\nRISK: medium\n\n"
        "Every new file edits project.pbxproj.\n"
    )

    def test_parses_blocks(self):
        s = rules.parse_suggestions(self.SUGGESTIONS, TARGETS)
        self.assertEqual([x["title"] for x in s],
                         ["Add pull-to-refresh to the iOS feed", "Convert to synchronized folders"])
        self.assertEqual(s[0]["kind"], "parity")
        self.assertEqual(s[0]["platforms"], ["ios"])
        self.assertTrue(s[0]["body"].startswith("Android refreshes"))
        self.assertEqual(s[1]["body"], "Every new file edits project.pbxproj.")

    def test_none_is_fine(self):
        self.assertEqual(rules.parse_suggestions("# Suggestions\n\nNothing worth filing.\n", TARGETS), [])

    def test_bad_kind(self):
        with self.assertRaises(Refused):
            rules.parse_suggestions("## Suggestion: X\nKIND: vibes\nPLATFORMS: ios\nRISK: low\n\nBody\n", TARGETS)

    def test_needs_body(self):
        with self.assertRaises(Refused):
            rules.parse_suggestions("## Suggestion: X\nKIND: quality\nPLATFORMS: ios\nRISK: low\n", TARGETS)

    def test_profile_target(self):
        self.assertEqual(rules.parse_profile("TARGET: ios\nSCHEME: App\n\n# x\n", "ios")["SCHEME"], "App")
        with self.assertRaises(Refused):
            rules.parse_profile("TARGET: android\n\n# x\n", "ios")


if __name__ == "__main__":
    unittest.main()
