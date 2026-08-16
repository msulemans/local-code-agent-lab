# Discount is missing at the eligibility boundary

Orders become eligible for a ten-percent discount when the subtotal reaches
100. The current implementation incorrectly returns no discount at exactly
100 while values above the boundary work. Preserve behavior below and above
the boundary.
