# Parser crashes when input is absent

Calling `parse_value(None)` raises an exception. Treat an absent value like an
empty string while preserving the existing whitespace trimming behavior.
