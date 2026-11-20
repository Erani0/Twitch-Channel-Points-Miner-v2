POLL_ALL_WATCHED = True


def should_poll(drop_stream):
    return drop_stream is True or POLL_ALL_WATCHED
