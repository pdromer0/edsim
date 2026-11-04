"""One Manchester level palette for service plans and level-based charts."""

from types import MappingProxyType

LEVEL_COLORS = MappingProxyType(
    {
        1: "#ef5350",
        2: "#ff9800",
        3: "#ffeb3b",
        4: "#66bb6a",
        5: "#64b5f6",
    }
)
UNKNOWN_LEVEL_COLOR = "#cfd8dc"
