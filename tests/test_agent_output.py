from qqbridge.agent_output import parse_agent_plan


def test_parse_skip_plan() -> None:
    plan = parse_agent_plan('{"skip": true}')

    assert plan.should_skip


def test_plain_skip_plan() -> None:
    plan = parse_agent_plan("SKIP")

    assert plan.should_skip


def test_actions_plan_is_not_bridge_sent() -> None:
    plan = parse_agent_plan(
        '{"actions":[{"type":"send","reply_to":"42","text":"看到了"},{"type":"face","face_id":"14"}]}'
    )

    assert not plan.should_skip


def test_plain_text_is_internal_result_not_bridge_send() -> None:
    plan = parse_agent_plan("普通回复")

    assert not plan.should_skip
