# coding: utf-8


def assert_code(code, message):
    """
    Raises stored :class:`HTTPError`, if one occurred.
    """

    if 400 <= code < 500:
        raise RuntimeError('{} Client Error: {}'.format(
            code, message))

    elif 500 <= code < 600:
        raise RuntimeError('{} Server Error: {}'.format(
            code, message))
