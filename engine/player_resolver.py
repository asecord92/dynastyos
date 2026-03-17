import httpx
from .supabase_client import get_supabase

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"


def format_name(fantrax_name: str) -> str:
    """Convert 'Last, First' to 'First Last' for MLB Stats API lookup."""
    parts = fantrax_name.split(", ", 1)
    if len(parts) == 2:
        return f"{parts[1]} {parts[0]}"
    return fantrax_name


def get_existing_mapping(fantrax_id: str) -> dict | None:
    """Check if a mapping already exists in Supabase."""
    try:
        supabase = get_supabase()
        result = supabase.table("player_id_map").select("*").eq("fantrax_id", fantrax_id).execute()
        if result.data:
            return result.data[0]
    except Exception as e:
        print(f"[resolver] Supabase read error for {fantrax_id}: {e}")
    return None


def save_mapping(mapping: dict) -> None:
    """Persist a resolved mapping to Supabase."""
    try:
        supabase = get_supabase()
        supabase.table("player_id_map").upsert(mapping).execute()
    except Exception as e:
        print(f"[resolver] Supabase write error for {mapping.get('fantrax_id')}: {e}")


def resolve_player(
    fantrax_id: str,
    name: str,
    team: str,
) -> dict | None:
    """
    Resolves a Fantrax player ID to an MLB Stats API player ID.
    Checks Supabase cache first, falls back to MLB Stats API lookup.
    Returns a mapping dict or None if no match could be found.
    """
    # Check if already resolved
    existing = get_existing_mapping(fantrax_id)
    if existing:
        return existing

    formatted_name = format_name(name)

    try:
        resp = httpx.get(
            f"{MLB_STATS_BASE}/people/search",
            params={"names": formatted_name, "hydrate": "currentTeam"},
            timeout=10,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
    except Exception as e:
        print(f"[resolver] MLB API error for {name}: {e}")
        return None

    # Filter to active players only
    people = [p for p in people if p.get("active", False)]

    if len(people) == 0:
        print(f"[resolver] No match found for {name}")
        return None

    if len(people) == 1:
        person = people[0]
        mlb_team = person.get("currentTeam", {}).get("name", "")
        mapping = {
            "fantrax_id": fantrax_id,
            "mlb_id": person["id"],
            "full_name": person["fullName"],
            "mlb_team": mlb_team,
            "confidence": "exact",
        }
        save_mapping(mapping)
        return mapping

    # Multiple results — try to disambiguate by team
    team_lower = team.lower()
    for person in people:
        current_team = person.get("currentTeam", {})
        team_name = current_team.get("name", "").lower()
        team_abbr = current_team.get("abbreviation", "").lower()
        if team_lower in (team_name, team_abbr) or team_lower in team_name:
            mlb_team = current_team.get("name", "")
            mapping = {
                "fantrax_id": fantrax_id,
                "mlb_id": person["id"],
                "full_name": person["fullName"],
                "mlb_team": mlb_team,
                "confidence": "fuzzy",
            }
            save_mapping(mapping)
            return mapping

    print(f"[resolver] Ambiguous match for {name} (team: {team}) — manual review needed")
    return None