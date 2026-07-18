from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from xlb import prepare_terminal_bbe  # noqa: E402


class XlbPreparationTests(unittest.TestCase):
    def test_excludes_fouls_and_uses_per_pa_stand(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "game_date": "2026-06-09",
                    "game_pk": 1,
                    "at_bat_number": 1,
                    "pitch_number": 3,
                    "pitcher": 10,
                    "events": None,
                    "launch_speed": 105,
                    "launch_angle": 28,
                    "hc_x": 95,
                    "stand": "L",
                },
                {
                    "game_date": "2026-06-09",
                    "game_pk": 1,
                    "at_bat_number": 2,
                    "pitch_number": 4,
                    "pitcher": 10,
                    "events": "home_run",
                    "launch_speed": 105,
                    "launch_angle": 28,
                    "hc_x": 95,
                    "stand": "L",
                },
                {
                    "game_date": "2026-06-09",
                    "game_pk": 1,
                    "at_bat_number": 3,
                    "pitch_number": 2,
                    "pitcher": 10,
                    "events": "field_out",
                    "launch_speed": 96,
                    "launch_angle": 20,
                    "hc_x": 150,
                    "stand": "R",
                },
            ]
        )

        prepared = prepare_terminal_bbe(frame)

        self.assertEqual(len(prepared), 2)
        self.assertTrue(prepared["events"].notna().all())
        self.assertEqual(prepared["spray_side"].tolist(), ["oppo", "oppo"])

    def test_keeps_one_terminal_row_per_pa(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "game_date": "2026-06-09",
                    "game_pk": 1,
                    "at_bat_number": 1,
                    "pitch_number": pitch_number,
                    "pitcher": 10,
                    "events": "field_out",
                    "launch_speed": 90 + pitch_number,
                    "launch_angle": 20,
                    "hc_x": 120,
                    "stand": "R",
                }
                for pitch_number in [2, 3]
            ]
        )

        prepared = prepare_terminal_bbe(frame)

        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared.iloc[0]["pitch_number"], 3)


if __name__ == "__main__":
    unittest.main()
