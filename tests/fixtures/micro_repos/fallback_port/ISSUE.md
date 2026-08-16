# Missing port uses an invalid fallback

When no port value is configured, the service should use port 8080. Explicit
numeric values must continue to be converted to integers. The test output also
contains an unrelated offline-network warning that is not the cause.
