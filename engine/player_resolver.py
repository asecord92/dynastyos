import httpx
from .supabase_client import get_supabase
from .mlb_stats_client import fetch_roster_status

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"


def format_name(fantrax_name: str) -> str:
    """Convert 'Last, First' to 'First Last' for MLB Stats API lookup."""
    parts = fantrax_name.split(", ", 1)
    if len(parts) == 2:
        return f"{parts[1]} {parts[0]}"
    return fantrax_name


def search_mlb(name: str) -> list:
    """Search MLB Stats API by name with currentTeam hydration."""
    try:
        resp = httpx.get(
            f"{MLB_STATS_BASE}/people/search",
            params={"names": name, "hydrate": "currentTeam"},
            timeout=10,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
        return [p for p in people if p.get("active", False)]
    except Exception as e:
        print(f"[resolver] MLB API error searching '{name}': {e}")
        return []


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


def pick_match(people: list, team: str) -> tuple[dict, str] | tuple[None, None]:
    """
    Given a list of MLB API people, try to pick the right one.
    Returns (person, confidence) or (None, None).
    """
    if len(people) == 1:
        return people[0], "exact"

    # Multiple results — disambiguate by team
    team_lower = team.lower()
    for person in people:
        current_team = person.get("currentTeam", {})
        team_name = current_team.get("name", "").lower()
        team_abbr = current_team.get("abbreviation", "").lower()
        if team_lower in (team_name, team_abbr) or team_lower in team_name:
            return person, "fuzzy"

    return None, None


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

    # Attempt 1 — full name search ("Leodalis De Vries")
    formatted_name = format_name(name)
    people = search_mlb(formatted_name)

    # Attempt 2 — last name only fallback for players who go by a nickname
    if len(people) == 0:
        last_name = name.split(", ")[0]  # "De Vries, Leodalis" → "De Vries"
        first_name = name.split(", ")[1] if ", " in name else ""
        candidates = search_mlb(last_name)
        # Filter by first name appearing in fullFMLName
        if first_name:
            people = [
                p for p in candidates
                if first_name.lower() in p.get("fullFMLName", "").lower()
            ]
        else:
            people = candidates

    if len(people) == 0:
        print(f"[resolver] No match found for {name}")
        return None

    person, confidence = pick_match(people, team)

    if person is None:
        print(f"[resolver] Ambiguous match for {name} (team: {team}) — manual review needed")
        return None

    mlb_team = person.get("currentTeam", {}).get("name", "")
    position_code = person.get("primaryPosition", {}).get("code", "")
    player_type = "pitcher" if position_code == "1" else "hitter"

    mapping = {
        "fantrax_id": fantrax_id,
        "mlb_id": person["id"],
        "full_name": person["fullName"],
        "mlb_team": mlb_team,
        "player_type": player_type,
        "confidence": confidence,
    }
    save_mapping(mapping)

    # Enrich with current roster status (separate update so ID mapping is saved even if this fails)
    try:
        status_data = fetch_roster_status(person["id"])
        supabase = get_supabase()
        supabase.table("player_id_map").update({
            "roster_status": status_data["roster_status"],
            "il_type": status_data["il_type"],
        }).eq("fantrax_id", fantrax_id).execute()
    except Exception as e:
        print(f"[resolver] Failed to update roster status for {fantrax_id}: {e}")

    return mapping


def refresh_roster_statuses(fantrax_ids: list[str]) -> None:
    """
    Refreshes roster_status and il_type for a list of fantrax IDs.
    Called after each full sync since roster status changes frequently
    unlike the underlying ID mappings.
    Never raises.
    """
    if not fantrax_ids:
        return

    try:
        supabase = get_supabase()
        result = (
            supabase.table("player_id_map")
            .select("fantrax_id,mlb_id")
            .in_("fantrax_id", fantrax_ids)
            .execute()
        )
        rows = result.data or []
    except Exception as e:
        print(f"[refresh_status] Failed to load player IDs: {e}")
        return

    print(f"[refresh_status] Refreshing roster status for {len(rows)} players...")
    updated = 0
    for row in rows:
        fantrax_id = row.get("fantrax_id", "")
        mlb_id = row.get("mlb_id")
        if not mlb_id:
            continue
        try:
            status_data = fetch_roster_status(int(mlb_id))
            update = {
                "roster_status": status_data["roster_status"],
                "il_type": status_data["il_type"],
            }
            # Refresh the team too — it's frozen at first resolution otherwise, so an
            # optioned-then-recalled player stays stuck on his old (AAA) team.
            if status_data.get("mlb_team"):
                update["mlb_team"] = status_data["mlb_team"]
            supabase.table("player_id_map").update(update).eq("fantrax_id", fantrax_id).execute()
            updated += 1
        except Exception as e:
            print(f"[refresh_status] Failed for {fantrax_id}: {e}")

    print(f"[refresh_status] Done — {updated}/{len(rows)} statuses updated")