# Empty samples crash ratio calculation

`success_ratio` raises division by zero when a sample has no attempts. Return
0.0 for an empty sample while preserving normal division for non-empty data.
