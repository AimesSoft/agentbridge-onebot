from qqbridge.models import coerce_segments, extract_plain_text, at_targets, reply_ids


def test_parse_cq_message() -> None:
    segments = coerce_segments("[CQ:reply,id=42][CQ:at,qq=10001] hello [CQ:image,file=a.jpg]")

    assert reply_ids(segments) == ["42"]
    assert at_targets(segments) == ["10001"]
    assert extract_plain_text(segments) == "hello [图片]"


def test_list_message_segments() -> None:
    segments = coerce_segments(
        [
            {"type": "at", "data": {"qq": 123}},
            {"type": "text", "data": {"text": " 你好"}},
        ]
    )

    assert at_targets(segments) == ["123"]
    assert extract_plain_text(segments) == "你好"

