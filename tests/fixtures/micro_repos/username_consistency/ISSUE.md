# Three-character usernames are rejected inconsistently

The product rule permits usernames with at least three non-space characters.
Both preview validation and account persistence currently reject names at the
exact three-character boundary. Keep both flows consistent and preserve the
rejection of shorter names.
