<!-- table: rob_point -->
| sample | horizon (days) | tickers | gradient boosting, median skill | gradient boosting better than flat | drift, median skill | any model better than flat | direction right (median) vs "always up" |
|---|---|---|---|---|---|---|---|
| main, all 20 | 5 | 20 | -4.2% | 0/20 | +0.2% | 0/80 | 51% vs 55% |
| main, all 20 | 20 | 20 | -8.6% | 0/20 | +0.7% | 2/80 | 52% vs 60% |
| main, all 20 | 60 | 20 | -8.4% | 0/20 | +3.8% | 6/80 | 58% vs 65% |
| main, ETFs only | 5 | 5 | -5.0% | 0/5 | +0.8% | 0/20 | 53% vs 59% |
| main, ETFs only | 20 | 5 | -6.9% | 0/5 | +3.3% | 2/20 | 56% vs 66% |
| main, ETFs only | 60 | 5 | -3.6% | 0/5 | +8.1% | 2/20 | 61% vs 75% |
| 2015-2021, all 20 | 5 | 20 | -3.1% | 0/20 | +0.3% | 1/80 | 52% vs 58% |
| 2015-2021, all 20 | 20 | 20 | -3.4% | 0/20 | +1.3% | 6/80 | 55% vs 62% |
| 2015-2021, all 20 | 60 | 20 | +0.1% | 2/20 | +3.7% | 14/80 | 63% vs 71% |
| 2015-2021, ETFs only | 5 | 5 | -3.2% | 0/5 | +0.2% | 0/20 | 52% vs 59% |
| 2015-2021, ETFs only | 20 | 5 | -5.8% | 0/5 | +0.9% | 2/20 | 53% vs 56% |
| 2015-2021, ETFs only | 60 | 5 | +2.9% | 0/5 | +1.2% | 4/20 | 60% vs 64% |

<!-- table: rob_vol -->
| sample | horizon (days) | EWMA, median skill vs recent vol | GJR-GARCH, median change vs EWMA | GARCH clearly better / worse than EWMA |
|---|---|---|---|---|
| main, all 20 | 5 | +1.4% | +3.0% | 7 / 6 of 20 |
| main, all 20 | 20 | +6.5% | +10.1% | 8 / 4 of 20 |
| main, all 20 | 60 | +10.1% | +20.2% | 12 / 5 of 20 |
| main, ETFs only | 5 | -0.0% | +3.6% | 2 / 2 of 5 |
| main, ETFs only | 20 | +0.7% | +5.9% | 1 / 1 of 5 |
| main, ETFs only | 60 | +2.3% | +6.2% | 2 / 2 of 5 |
| 2015-2021, all 20 | 5 | +0.4% | +4.7% | 13 / 3 of 20 |
| 2015-2021, all 20 | 20 | +4.5% | +10.2% | 10 / 1 of 20 |
| 2015-2021, all 20 | 60 | +5.7% | +17.8% | 14 / 1 of 20 |
| 2015-2021, ETFs only | 5 | -0.7% | +5.1% | 4 / 1 of 5 |
| 2015-2021, ETFs only | 20 | +3.3% | +11.5% | 4 / 0 of 5 |
| 2015-2021, ETFs only | 60 | +3.9% | +19.8% | 4 / 0 of 5 |

<!-- table: rob_conformal -->
| sample | horizon (days) | range used | conformal coverage, median (min-max) | normal band coverage, median (min-max) | independent test periods (median) |
|---|---|---|---|---|---|
| main, all 20 | 5 | 20/20 | 81% (77-84%) | 79% (73-82%) | 99 |
| main, all 20 | 20 | 20/20 | 81% (72-89%) | 78% (61-85%) | 23 |
| main, ETFs only | 5 | 5/5 | 81% (79-84%) | 79% (78-80%) | 99 |
| main, ETFs only | 20 | 5/5 | 80% (74-89%) | 81% (73-85%) | 23 |
| 2015-2021, all 20 | 5 | 20/20 | 81% (78-84%) | 81% (77-85%) | 150 |
| 2015-2021, all 20 | 20 | 20/20 | 80% (71-87%) | 78% (69-88%) | 36 |
| 2015-2021, ETFs only | 5 | 5/5 | 81% (79-82%) | 80% (79-84%) | 150 |
| 2015-2021, ETFs only | 20 | 5/5 | 82% (80-86%) | 75% (74-79%) | 36 |
