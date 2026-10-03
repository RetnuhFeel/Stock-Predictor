<!-- table: point -->
| horizon (days) | model | tickers | better than flat | inconclusive | not better | median skill | tickers with skill > 0 |
|---|---|---|---|---|---|---|---|
| 5 | Drift | 20 | 0 | 12 | 8 | +0.2% | 14/20 |
| 5 | EWMA | 20 | 0 | 1 | 19 | -1.5% | 1/20 |
| 5 | Ridge AR | 20 | 0 | 10 | 10 | -0.1% | 10/20 |
| 5 | Gradient boosting | 20 | 0 | 0 | 20 | -4.2% | 0/20 |
| 20 | Drift | 20 | 1 | 13 | 6 | +0.7% | 14/20 |
| 20 | EWMA | 20 | 0 | 2 | 18 | -4.3% | 2/20 |
| 20 | Ridge AR | 20 | 1 | 8 | 11 | -0.8% | 9/20 |
| 20 | Gradient boosting | 20 | 0 | 1 | 19 | -8.6% | 1/20 |
| 60 | Drift | 20 | 5 | 8 | 7 | +3.8% | 13/20 |
| 60 | EWMA | 20 | 0 | 4 | 16 | -12.6% | 4/20 |
| 60 | Ridge AR | 20 | 1 | 11 | 8 | +1.2% | 12/20 |
| 60 | Gradient boosting | 20 | 0 | 1 | 19 | -8.4% | 1/20 |

<!-- table: direction -->
| horizon (days) | model right about direction (median) | "always up" would score (median) | tickers where model beat "always up" |
|---|---|---|---|
| 5 | 51% | 55% | 5/20 |
| 20 | 52% | 60% | 1/20 |
| 60 | 58% | 65% | 1/20 |

<!-- table: volatility -->
| horizon (days) | model | median skill vs recent vol | better than recent vol | better than EWMA | worse than EWMA | median change vs EWMA |
|---|---|---|---|---|---|---|
| 5 | EWMA volatility | +1.4% | 6/20 | (headline) |  |  |
| 5 | HAR | +8.5% | 15/20 | 16/20 | 0/20 | +7.5% |
| 5 | GJR-GARCH | +4.1% | 7/20 | 7/20 | 6/20 | +3.0% |
| 20 | EWMA volatility | +6.5% | 13/20 | (headline) |  |  |
| 20 | HAR | +13.6% | 10/20 | 8/20 | 3/20 | +7.8% |
| 20 | GJR-GARCH | +13.7% | 10/20 | 8/20 | 4/20 | +10.1% |
| 60 | EWMA volatility | +10.1% | 16/20 | (headline) |  |  |
| 60 | HAR | +18.5% | 14/20 | 14/20 | 4/20 | +12.7% |
| 60 | GJR-GARCH | +23.6% | 14/20 | 12/20 | 5/20 | +20.2% |
| 120 | EWMA volatility | +11.0% | 0/20 | (headline) |  |  |
| 120 | HAR | +30.7% | 0/20 | 0/20 | 3/20 | +24.3% |
| 120 | GJR-GARCH | +40.0% | 0/20 | 0/20 | 4/20 | +30.9% |

<!-- table: conformal -->
| horizon (days) | range used | conformal coverage, median (min-max) | normal band coverage, median (min-max) | typical multiplier (normal = 1.28) | independent test periods (median) |
|---|---|---|---|---|---|
| 5 | 20/20 | 81% (77-84%) | 79% (73-82%) | 1.33 | 99 |
| 20 | 20/20 | 81% (72-89%) | 78% (61-85%) | 1.40 | 23 |
| 60 | 0/20 | 77% (62-99%) | 78% (52-96%) | 1.47 | 6 |
| 120 | 20/20 | 81% (67-95%) | 77% (62-89%) | 1.40 | 16 |
| 180 | 20/20 | 78% (62-98%) | 70% (58-88%) | 1.59 | 9 |
| 256 | 0/20 | 86% (67-100%) | 73% (55-94%) | 1.74 | 5 |

<!-- table: leakage -->
| how the model was scored | median skill vs flat | tickers with skill > 0 |
|---|---|---|
| shuffled k-fold (leaky) | +10.6% | 20/20 |
| walk-forward, no embargo | -8.2% | 1/20 |
| walk-forward + embargo (used) | -8.6% | 1/20 |
