def resolve_port(raw: str | None) -> int:
    if raw is None:
        return 0
    return int(raw)
