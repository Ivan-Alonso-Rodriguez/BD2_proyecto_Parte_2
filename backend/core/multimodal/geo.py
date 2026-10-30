"""Geografía esférica WGS84 aproximada con radio medio terrestre en km."""
import math

EARTH_KM = 6371.0088


def haversine(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 2*EARTH_KM*math.asin(math.sqrt(min(1., max(0., h))))


def radius_windows(lon, lat, radius):
    if not (-180 <= lon <= 180 and -90 <= lat <= 90 and 0 <= radius <= math.pi*EARTH_KM):
        raise ValueError("Coordenadas o radio geográfico inválidos")
    angular = radius/EARTH_KM
    low, high = max(-90., lat-math.degrees(angular)), min(90., lat+math.degrees(angular))
    if low == -90 or high == 90:
        return [(-180., low, 180., high)]
    delta = math.degrees(math.asin(min(1., math.sin(angular)/math.cos(math.radians(lat)))))
    left, right = lon-delta, lon+delta
    if left < -180:
        return [(left+360, low, 180., high), (-180., low, right, high)]
    if right > 180:
        return [(left, low, 180., high), (-180., low, right-360, high)]
    return [(left, low, right, high)]


def geographic_mindist(point, box):
    """Distancia mínima exacta a un rectángulo lon/lat sin cruzar antimeridiano.

    Maximiza el producto escalar entre el punto y la superficie esférica del MBR.
    Sirve como cota admisible y como distancia exacta para hojas puntuales.
    """
    lon, lat = point
    xmin, ymin, xmax, ymax = box
    if xmin <= lon <= xmax:
        delta = 0.
    else:
        delta = min(abs((lon-edge+180)%360-180) for edge in (xmin, xmax))
    phi, delta = math.radians(lat), math.radians(delta)
    a, b = math.sin(phi), math.cos(phi)*math.cos(delta)
    candidates = [math.radians(ymin), math.radians(ymax)]
    optimum = math.atan2(a, b)
    if candidates[0] <= optimum <= candidates[1]:
        candidates.append(optimum)
    dot = max(a*math.sin(y)+b*math.cos(y) for y in candidates)
    return EARTH_KM*math.acos(max(-1., min(1., dot)))
