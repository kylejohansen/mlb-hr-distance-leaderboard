# Getting Cooked inverted LBI diagnostic

## Verdict

**Do not make inverted LBI severity per event the Getting Cooked formula. It is distinct and narratively useful, but the signal is too unstable and does not carry future HR/BBE.**

The tested inversion uses LBI v1.4's physics-only gate: launch angle 14-50 degrees, actual HR with 1+ standard parks, plus non-HR contact with 8+ standard parks. It is terminal-BBE scoped and regular-season scoped.

Qualified pool: 1,539 pitcher-seasons at 100+ terminal BBE and 8+ LBI-eligible events.

## What Improved Means

This diagnostic treats improvement as: distinct from plain HR-capable frequency, more stable or at least no noisier than the current rate story, and meaningfully related to future longball damage allowed. It does not optimize a production formula.

## Coverage

| Season | Terminal BBE | HRT rows | Joined | Join% | LBI events | Qualified | Hot Dog joined |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2021.000 | 121323.000 | 9606.000 | 9327.000 | 0.971 | 7242.000 | 316.000 | 436.000 |
| 2022.000 | 123732.000 | 8936.000 | 8672.000 | 0.970 | 6480.000 | 285.000 | 384.000 |
| 2023.000 | 123886.000 | 9716.000 | 9426.000 | 0.970 | 7184.000 | 314.000 | 397.000 |
| 2024.000 | 123707.000 | 9167.000 | 8924.000 | 0.973 | 6745.000 | 314.000 | 408.000 |
| 2025.000 | 124362.000 | 9575.000 | 9295.000 | 0.971 | 6917.000 | 310.000 | 408.000 |

## Distinctness

| Candidate | Compared to | n | Pearson | Spearman |
| --- | --- | --- | --- | --- |
| Inverted LBI severity per event | HR-capable/LBI events per BBE | 1539 | -0.018 | -0.018 |
| Inverted LBI severity per event | Current Getting Cooked composite | 1524 | 0.162 | 0.148 |
| Inverted LBI severity per event | Barrel% allowed | 1539 | 0.115 | 0.112 |
| Inverted LBI severity per event | Adjusted xHR/BBE allowed | 1524 | 0.017 | 0.013 |
| Inverted LBI severity per event | Actual HR/BBE | 1539 | -0.007 | -0.013 |
| Inverted LBI per BBE blend | HR-capable/LBI events per BBE | 1539 | 0.981 | 0.981 |
| Inverted LBI per BBE blend | Current Getting Cooked composite | 1524 | 0.782 | 0.788 |
| Inverted LBI per BBE blend | Barrel% allowed | 1539 | 0.708 | 0.689 |
| Inverted LBI per BBE blend | Adjusted xHR/BBE allowed | 1524 | 0.845 | 0.846 |
| Inverted LBI per BBE blend | Actual HR/BBE | 1539 | 0.851 | 0.849 |
| Rate x severity blend | HR-capable/LBI events per BBE | 1539 | 0.981 | 0.982 |
| Rate x severity blend | Current Getting Cooked composite | 1524 | 0.782 | 0.788 |
| Rate x severity blend | Barrel% allowed | 1539 | 0.708 | 0.689 |
| Rate x severity blend | Adjusted xHR/BBE allowed | 1524 | 0.844 | 0.846 |
| Rate x severity blend | Actual HR/BBE | 1539 | 0.851 | 0.850 |

## Stability

| Metric | n | YoY Pearson | YoY Spearman |
| --- | --- | --- | --- |
| Current Getting Cooked composite | 687 | 0.202 | 0.218 |
| HR-capable/LBI events per BBE | 696 | 0.254 | 0.279 |
| Inverted LBI severity per event | 696 | 0.122 | 0.110 |
| Inverted LBI per BBE blend | 696 | 0.237 | 0.260 |
| Rate x severity blend | 696 | 0.237 | 0.260 |
| Actual HR/BBE | 696 | 0.180 | 0.216 |
| Barrel% allowed | 696 | 0.198 | 0.213 |

## Future HR/BBE Validity

| Current predictor | n | Pearson | Spearman |
| --- | --- | --- | --- |
| HR-capable/LBI events per BBE | 696 | 0.198 | 0.224 |
| Rate x severity blend | 696 | 0.187 | 0.214 |
| Inverted LBI per BBE blend | 696 | 0.187 | 0.214 |
| Actual HR/BBE | 696 | 0.174 | 0.212 |
| Adjusted xHR/BBE allowed | 690 | 0.172 | 0.184 |
| Current Getting Cooked composite | 690 | 0.161 | 0.171 |
| Barrel% allowed | 696 | 0.137 | 0.164 |
| Inverted LBI severity per event | 696 | -0.065 | -0.070 |

## Top-25 Overlap

| Left | Right | Top N | Overlap | Overlap% |
| --- | --- | --- | --- | --- |
| Inverted LBI per BBE blend | Rate x severity blend | 25 | 25 | 1.000 |
| HR-capable/LBI events per BBE | Inverted LBI per BBE blend | 25 | 20 | 0.800 |
| HR-capable/LBI events per BBE | Rate x severity blend | 25 | 20 | 0.800 |
| Current Getting Cooked composite | Inverted LBI per BBE blend | 25 | 12 | 0.480 |
| Current Getting Cooked composite | Rate x severity blend | 25 | 12 | 0.480 |
| Current Getting Cooked composite | HR-capable/LBI events per BBE | 25 | 11 | 0.440 |
| Inverted LBI severity per event | Rate x severity blend | 25 | 6 | 0.240 |
| Inverted LBI per BBE blend | Inverted LBI severity per event | 25 | 6 | 0.240 |
| Current Getting Cooked composite | Inverted LBI severity per event | 25 | 5 | 0.200 |
| HR-capable/LBI events per BBE | Inverted LBI severity per event | 25 | 3 | 0.120 |

## 2025 Case Studies

| Case | Pitcher | Team | Role | BBE | LBI events | Cooked | Rate+ | Severity+ | Per-BBE+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| High severity, lower frequency | Kumar Rocker | TEX | SP | 203 | 12.000 | 128.400 | 106.281 | 116.018 | 123.314 |
| High severity, lower frequency | Trevor Rogers | BAL | SP | 289 | 10.000 | 71.700 | 62.212 | 116.004 | 72.174 |
| High severity, lower frequency | Tim Hill | NYY | RP | 213 | 10.000 | 74.500 | 84.409 | 113.213 | 95.570 |
| High severity, lower frequency | Daniel Lynch IV | KC | RP | 211 | 10.000 | 86.700 | 85.209 | 111.798 | 95.270 |
| High severity, lower frequency | George Kirby | SEA | SP | 350 | 15.000 | 97.600 | 77.054 | 111.662 | 86.046 |
| High severity, lower frequency | Dustin May | BOS | SP | 392 | 23.000 | 124.500 | 105.490 | 110.616 | 116.698 |
| High severity, lower frequency | Framber Valdez | HOU | SP | 539 | 18.000 | 55.100 | 60.042 | 110.526 | 66.367 |
| High severity, lower frequency | Tony Santillan | CIN | RP | 192 | 8.000 | 79.400 | 74.913 | 109.012 | 81.671 |
| High severity, lower frequency | Jake Bird | NYY | RP | 154 | 9.000 | 89.300 | 105.073 | 108.560 | 114.077 |
| High severity, lower frequency | Shane Smith | CWS | SP | 398 | 20.000 | 97.800 | 90.348 | 108.420 | 97.963 |
| High severity, lower frequency | Michael McGreevy | STL | SP | 317 | 14.000 | 75.200 | 79.403 | 107.819 | 85.619 |
| High severity, lower frequency | Ranger Suarez | PHI | SP | 455 | 14.000 | 75.000 | 55.321 | 107.692 | 59.581 |
| High severity, lower frequency | Freddy Peralta | MIL | SP | 444 | 22.000 | 108.200 | 89.086 | 107.451 | 95.731 |
| High severity, lower frequency | Noah Cameron | KC | SP | 396 | 21.000 | 109.600 | 95.344 | 107.426 | 102.433 |
| High severity, lower frequency | José Soriano | LAA | SP | 485 | 14.000 | 42.000 | 51.899 | 106.549 | 55.302 |
| High severity, lower frequency | Enyel De Los Santos | HOU | RP | 192 | 9.000 | 101.100 | 84.277 | 106.312 | 89.604 |
| High severity, lower frequency | Tyler Kinley | ATL | RP | 199 | 10.000 | 76.800 | 90.348 | 106.254 | 96.006 |
| High severity, lower frequency | Jack Leiter | TEX | SP | 425 | 23.000 | 111.300 | 97.299 | 105.993 | 103.138 |
| High severity, lower frequency | Michael Wacha | KC | SP | 538 | 24.000 | 81.100 | 80.205 | 105.953 | 84.986 |
| High severity, lower frequency | Hunter Brown | HOU | SP | 458 | 24.000 | 71.900 | 94.214 | 105.914 | 99.794 |
| High severity, lower frequency | Kris Bubic | KC | SP | 317 | 9.000 | 33.200 | 51.045 | 105.746 | 53.982 |
| High severity, lower frequency | Cristopher Sánchez | PHI | SP | 542 | 18.000 | 47.400 | 59.709 | 105.542 | 63.024 |
| High severity, lower frequency | Kevin Gausman | TOR | SP | 531 | 22.000 | 82.300 | 74.490 | 105.361 | 78.490 |
| High severity, lower frequency | Reese Olson | DET | SP | 189 | 8.000 | 74.400 | 76.102 | 105.037 | 79.942 |
| High severity, lower frequency | Pablo López | MIN | SP | 215 | 9.000 | 90.600 | 75.262 | 104.973 | 79.011 |
| High frequency, lower severity | Chad Green | TOR | RP | 139 | 16.000 | 165.100 | 206.955 | 95.124 | 196.880 |
| High frequency, lower severity | Anthony DeSclafani | AZ | RP | 116 | 12.000 | 159.400 | 185.992 | 97.134 | 180.675 |
| High frequency, lower severity | Jordan Romano | PHI | RP | 120 | 12.000 | 118.000 | 179.792 | 90.337 | 162.431 |
| High frequency, lower severity | Génesis Cabrera | MIN | RP | 132 | 13.000 | 115.700 | 177.068 | 95.848 | 169.729 |
| High frequency, lower severity | Ryan Zeferjahn | LAA | RP | 145 | 14.000 | 124.300 | 173.592 | 90.449 | 157.024 |

## Quick Reads

- Severity vs HR-capable/LBI event frequency: r=-0.018.
- Severity vs current Getting Cooked: r=0.162.
- Per-BBE inverted LBI blend vs HR-capable/LBI event frequency: r=0.981.
- Per-BBE inverted LBI blend vs current Getting Cooked: r=0.782.
- YoY severity stability: r=0.122; rate stability: r=0.254; blend stability: r=0.237.
- Future HR/BBE: current Cooked r=0.161, rate r=0.198, severity r=-0.065, per-BBE blend r=0.187, actual HR/BBE r=0.174.
