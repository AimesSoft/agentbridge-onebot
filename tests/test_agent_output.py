from qqbridge.agent_output import parse_agent_plan


def test_parse_skip_plan() -> None:
    plan = parse_agent_plan('{"skip": true}')

    assert plan.should_skip


def test_parse_actions_plan() -> None:
    plan = parse_agent_plan(
        '{"actions":[{"type":"send","reply_to":"42","text":"看到了"},{"type":"face","face_id":"14"}]}'
    )

    assert not plan.should_skip
    assert plan.actions[0].text == "看到了"
    assert plan.actions[0].reply_to == "42"
    assert plan.actions[1].type == "face"
    assert plan.actions[1].face_id == "14"


def test_plain_text_falls_back_to_send() -> None:
    plan = parse_agent_plan("普通回复")

    assert plan.actions[0].text == "普通回复"

