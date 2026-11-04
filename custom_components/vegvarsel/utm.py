"""ETRS89 / UTM zone 33N (EPSG:25833) to latitude/longitude.

Statens vegvesen gives a stretch of road as a GML line in UTM 33 metres. This
is the inverse transverse Mercator in Krüger's series (as in Karney 2011),
good to well under a millimetre within the zone and to centimetres across all
of Norway, which UTM 33 is stretched over. ETRS89 and WGS84 differ by well
under a metre, far below any corridor.
"""

from __future__ import annotations

from math import atan, atanh, cos, cosh, degrees, radians, sin, sinh, sqrt, tan

_A = 6378137.0
_F = 1 / 298.257222101  # GRS80
_K0 = 0.9996
_E0 = 500_000.0
_LON0 = radians(15.0)  # zone 33

_N = _F / (2 - _F)
_A_RECT = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_BETA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96,
    _N**2 / 48 + _N**3 / 15,
    17 * _N**3 / 480,
)
_E = sqrt(_F * (2 - _F))


def utm33_to_latlon(easting: float, northing: float) -> tuple[float, float]:
    xi = northing / (_K0 * _A_RECT)
    eta = (easting - _E0) / (_K0 * _A_RECT)
    xi_p, eta_p = xi, eta
    for j, b in enumerate(_BETA, start=1):
        xi_p -= b * sin(2 * j * xi) * cosh(2 * j * eta)
        eta_p -= b * cos(2 * j * xi) * sinh(2 * j * eta)
    chi = atan(sin(xi_p) / sqrt(sinh(eta_p) ** 2 + cos(xi_p) ** 2))
    lon = _LON0 + atan(sinh(eta_p) / cos(xi_p))
    # conformal latitude -> geodetic latitude, by Newton iteration on tan(phi)
    tau_p = tan(chi)
    tau = tau_p
    for _ in range(6):
        sigma = sinh(_E * atanh(_E * tau / sqrt(1 + tau * tau)))
        tau_i = tau * sqrt(1 + sigma * sigma) - sigma * sqrt(1 + tau * tau)
        d_tau = (tau_p - tau_i) / sqrt(1 + tau_i * tau_i) * (1 + (1 - _E**2) * tau * tau) / (
            (1 - _E**2) * sqrt(1 + tau * tau)
        )
        tau += d_tau
        if abs(d_tau) < 1e-12:
            break
    return degrees(atan(tau)), degrees(lon)
