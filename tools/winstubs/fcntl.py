"""Local-only stand-in for the Unix fcntl module, so Home Assistant's test
harness can be imported on Windows. Never shipped; CI runs on Linux."""

LOCK_EX = LOCK_NB = LOCK_SH = LOCK_UN = 0


def flock(*_args, **_kwargs):
    return None


def fcntl(*_args, **_kwargs):
    return 0


def ioctl(*_args, **_kwargs):
    return 0
