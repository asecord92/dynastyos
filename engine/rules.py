from pydantic import BaseModel

class LeagueRules(BaseModel):
    in_season_cap: float = 450.0
    offseason_cap: float = 335.0
    year2_raise: float = 1.0
    option_raise: float = 1.0
    extend_raise: float = 4.0
    extend_floor: float = 15.0
    extend_cap: float = 70.0