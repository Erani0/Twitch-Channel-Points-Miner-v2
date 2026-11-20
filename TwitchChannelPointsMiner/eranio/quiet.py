import logging

NOISY_FUNCTIONS = {"__active_incomplete_drop_deadline", "__log_category"}
NOISY_PREFIXES = ("Campaign: ", "Drop: ")
LOGGER_NAME = "TwitchChannelPointsMiner.classes.Twitch"


class DemoteNoisyInfo(logging.Filter):
    def filter(self, record):
        if record.levelno != logging.INFO:
            return True
        noisy = record.funcName in NOISY_FUNCTIONS
        if not noisy and record.funcName == "send_minute_watched_events":
            try:
                message = record.getMessage()
            except Exception:
                message = ""
            noisy = message.startswith(NOISY_PREFIXES)
        if noisy:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


def install():
    target = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(f, DemoteNoisyInfo) for f in target.filters):
        target.addFilter(DemoteNoisyInfo())
