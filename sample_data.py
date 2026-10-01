"""Sample rows for the single sheet (receivable = +ve, payable = -ve)."""
CR = 10_000_000
# Ref, Party, Amount, Date (expected / due), Actual Date, Probability, Priority
SAMPLE_ROWS = [
    ["INV-001", "Alpha Traders",   2 * CR,   "2026-01-20", "2026-01-20", 0.90, ""],
    ["INV-002", "Sigma Retail",    4 * CR,   "2026-02-02", "2026-02-02", 0.85, ""],
    ["INV-003", "Delta Infra",     8 * CR,   "2026-02-10", "2026-02-10", 0.95, ""],
    ["INV-004", "Omega Industries", 3.5 * CR, "2026-03-01", "2026-03-01", 0.90, ""],
    ["INV-005", "Beta Systems",    5 * CR,   "2026-03-14", "",           0.80, ""],
    ["INV-006", "Gamma Exports",   9 * CR,   "2026-04-04", "",           0.70, ""],
    ["PAY-001", "Salaries",        -1.5 * CR, "2026-01-31", "", "", 1],
    ["PAY-002", "Office & Rent",   -2.5 * CR, "2026-02-27", "", "", 2],
    ["PAY-003", "GST / Tax",       -3 * CR,   "2026-02-13", "", "", 1],
    ["PAY-004", "Raw Materials",   -6 * CR,   "2026-03-10", "", "", 2],
    ["PAY-005", "Capex Vendor",    -4 * CR,   "2026-04-15", "", "", 3],
]