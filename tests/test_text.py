from qqbridge.text import is_skip_response, split_qq_message


def test_skip_response() -> None:
    assert is_skip_response("SKIP")
    assert is_skip_response(" skip。")
    assert is_skip_response("不回复")
    assert not is_skip_response("skip this step")


def test_split_message() -> None:
    chunks = split_qq_message("abc\ndefgh", 5)

    assert chunks == ["abc", "defgh"]

