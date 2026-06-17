from pydantic import BaseModel, Field


class ScoringCategories(BaseModel):
    """The league's scoring categories, by player type. Defaults are the
    Inglorious Bashers (MLB) categories."""
    hitting: list[str] = ["R", "HR", "RBI", "SB", "OBP"]
    pitching: list[str] = ["QS", "SV", "K", "ERA", "WHIP"]


class ContractRules(BaseModel):
    """Dynasty contract trajectory. Present for contract leagues; set to
    ``None`` on :class:`LeagueRules` for leagues with no contracts (e.g. most
    Sleeper football leagues), in which case the contract section is omitted
    from the generated system prompt entirely."""
    year2_raise: float = 1.0
    option_raise: float = 1.0
    extend_raise: float = 4.0
    extend_floor: float = 15.0
    extend_cap: float = 70.0


class LeagueRules(BaseModel):
    """Per-league rules. Previously these were hardcoded constants duplicated
    into the trade system prompt; they now live on the ``leagues`` row so each
    league (and eventually each sport) produces an accurate prompt. Defaults
    reproduce the original hardcoded baseball values so existing behavior is
    unchanged when a league has no stored rules yet."""
    sport: str = "MLB"
    league_size: int = 10
    in_season_cap: float = 450.0
    offseason_cap: float = 335.0
    scoring: ScoringCategories = Field(default_factory=ScoringCategories)
    contract: ContractRules | None = Field(default_factory=ContractRules)


def load_rules(league: dict | None) -> LeagueRules:
    """Build :class:`LeagueRules` from a ``leagues`` row. Honors a stored
    ``rules`` JSON blob when present; otherwise falls back to defaults (keyed to
    the league's sport). Malformed stored rules fall back to defaults rather
    than raising, so a bad row never breaks trade analysis."""
    league = league or {}
    raw = league.get("rules")
    if raw:
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raw = None
        if isinstance(raw, dict):
            try:
                return LeagueRules(**raw)
            except Exception:
                pass
    sport = league.get("sport") or "MLB"
    # Non-MLB leagues with no stored rules default to no contract terms — the
    # contract trajectory is a baseball-house-rule, not a universal default.
    if sport != "MLB":
        return LeagueRules(sport=sport, contract=None)
    return LeagueRules(sport=sport)
