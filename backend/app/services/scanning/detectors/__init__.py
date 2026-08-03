from app.services.scanning.detectors.compose import DOCKER_COMPOSE
from app.services.scanning.registry import Detector

#: Every registered detector. Adding one is an import plus an entry here.
DETECTORS: list[Detector] = [DOCKER_COMPOSE]

# Enforced here, not only in a test: two detectors sharing a name would total
# silently into one report rather than failing, and the scan would look
# complete while one detector's results vanished.
_names = [d.name for d in DETECTORS]
if len(_names) != len(set(_names)):
    raise RuntimeError(f"duplicate detector name in DETECTORS: {_names}")
