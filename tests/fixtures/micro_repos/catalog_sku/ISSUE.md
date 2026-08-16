# Catalogue lookup misses equivalent SKUs

Catalogue keys are stored in uppercase. Looking up a SKU copied from a form
should ignore surrounding whitespace and letter case, but lowercase input is
currently reported as missing. Preserve the existing catalogue API.
