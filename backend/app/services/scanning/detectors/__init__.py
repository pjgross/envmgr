from app.services.scanning.detectors.compose import DOCKER_COMPOSE
from app.services.scanning.registry import Detector

#: Every registered detector. Adding one is an import plus an entry here.
DETECTORS: list[Detector] = [DOCKER_COMPOSE]
