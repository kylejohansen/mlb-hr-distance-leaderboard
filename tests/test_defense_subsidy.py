from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from defense_subsidy import (  # noqa: E402
    _aggregate_pitchers,
    _aggregate_teams,
    feature_frame,
    prepare_current_bip,
    run_identity_checks,
)


class DefenseSubsidyTests(unittest.TestCase):
    def test_prepare_current_bip_applies_terminal_non_hr_contract(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "game_date": "2026-04-01",
                    "game_pk": 1,
                    "at_bat_number": 1,
                    "pitch_number": 1,
                    "pitcher": 10,
                    "player_name": "Pitcher, Test",
                    "events": None,
                    "type": "S",
                    "description": "called_strike",
                    "launch_speed": None,
                    "launch_angle": None,
                    "bb_type": None,
                    "home_team": "CHC",
                    "away_team": "STL",
                    "inning_topbot": "Top",
                },
                {
                    "game_date": "2026-04-01",
                    "game_pk": 1,
                    "at_bat_number": 1,
                    "pitch_number": 2,
                    "pitcher": 10,
                    "player_name": "Pitcher, Test",
                    "events": "field_out",
                    "type": "X",
                    "description": "hit_into_play",
                    "launch_speed": 91.0,
                    "launch_angle": 8.0,
                    "bb_type": "ground_ball",
                    "home_team": "CHC",
                    "away_team": "STL",
                    "inning_topbot": "Top",
                },
                {
                    "game_date": "2026-04-01",
                    "game_pk": 1,
                    "at_bat_number": 2,
                    "pitch_number": 1,
                    "pitcher": 10,
                    "player_name": "Pitcher, Test",
                    "events": "home_run",
                    "type": "X",
                    "description": "hit_into_play_score",
                    "launch_speed": 108.0,
                    "launch_angle": 28.0,
                    "bb_type": "fly_ball",
                    "home_team": "CHC",
                    "away_team": "STL",
                    "inning_topbot": "Top",
                },
            ]
        )

        prepared = prepare_current_bip(frame, 2026, None)

        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared.iloc[0]["event_norm"], "field_out")
        self.assertEqual(prepared.iloc[0]["team"], "CHC")
        self.assertEqual(prepared.iloc[0]["pitcher_name"], "Test Pitcher")

    def test_feature_contract_is_stable(self) -> None:
        frame = pd.DataFrame(
            [{"launch_speed": 90.0, "launch_angle": 5.0, "bb_type": "ground_ball"}]
        )
        features = feature_frame(frame)
        self.assertEqual(
            features.columns.tolist(),
            ["launch_speed", "launch_angle", "bb_ground", "bb_line", "bb_fly", "bb_popup"],
        )
        self.assertEqual(features.iloc[0]["bb_ground"], 1.0)

    def test_team_weighted_identity_includes_subqualifier_pitchers(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "team": "CHC",
                    "pitcher_id": 1,
                    "pitcher_name": "Qualified",
                    "actual_woba": 0.10,
                    "expected_woba": 0.30,
                    "defenseSubsidy": -0.20,
                },
                {
                    "team": "CHC",
                    "pitcher_id": 1,
                    "pitcher_name": "Qualified",
                    "actual_woba": 0.20,
                    "expected_woba": 0.30,
                    "defenseSubsidy": -0.10,
                },
                {
                    "team": "CHC",
                    "pitcher_id": 2,
                    "pitcher_name": "Subqualifier",
                    "actual_woba": 0.40,
                    "expected_woba": 0.30,
                    "defenseSubsidy": 0.10,
                },
            ]
        )
        all_pitchers = _aggregate_pitchers(scored)
        teams = _aggregate_teams(scored)
        # Duplicate the single fake team to exercise identity only; the 30-team
        # production assertion is intentionally tested by the live run.
        with self.assertRaisesRegex(RuntimeError, "Expected 30 teams"):
            run_identity_checks(scored, all_pitchers, teams)
        weighted = (
            all_pitchers["defenseSubsidy"] * all_pitchers["bip"]
        ).sum() / all_pitchers["bip"].sum()
        self.assertAlmostEqual(weighted, teams.iloc[0]["defenseSubsidy"], places=12)


if __name__ == "__main__":
    unittest.main()
