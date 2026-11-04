"""Local-only stand-in for the Unix resource module (see fcntl.py)."""

RLIMIT_NOFILE = 7
RLIM_INFINITY = -1


def getrlimit(_resource):
    return (8192, 8192)


def setrlimit(_resource, _limits):
    return None
