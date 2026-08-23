from typing import List, Optional

from pydantic import BaseModel


class MatchpointOcupacion(BaseModel):
    """A single block drawn on the booking grid for one court. Any occupancy
    type (individual booking, open activity, club block, maintenance) means
    the covered period is NOT freely bookable. Times come pre-formatted as
    HH:MM in the centre's local timezone via the *Mostrar string fields - the
    /Date(...)/ epoch-millis fields are avoided deliberately."""

    Tipo: str
    Minutos: int
    StrHoraInicioMostrar: str
    StrHoraFinMostrar: str
    Id: int
    Color: str


class MatchpointHorarioFijo(BaseModel):
    Id: int


class MatchpointColumna(BaseModel):
    """One grid column: a single court (the club has 9)."""

    Id: str
    TextoPrincipal: str
    Tipo: str
    IdModalidadFijaParaReservas: int
    HorariosFijos: List[MatchpointHorarioFijo] = []
    Ocupaciones: List[MatchpointOcupacion] = []


class StratfordPadelCuadroResponse(BaseModel):
    """ASP.NET page-method payload of POST /booking/srvc.aspx/ObtenerCuadro,
    unwrapped from the {"d": {...}} envelope by the strategy. Grid runs
    StrHoraInicio..StrHoraFin (e.g. 08:00..22:00), PartesPorHora=2 means
    30-minute granularity."""

    Id: int
    Nombre: Optional[str]
    StrHoraInicio: Optional[str]
    StrHoraFin: Optional[str]
    StrFechaMin: Optional[str]
    StrFechaMax: Optional[str]
    PartesPorHora: int
    Columnas: List[MatchpointColumna] = []
