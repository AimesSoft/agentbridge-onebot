from __future__ import annotations


ONEBOT_CALL = "onebot.call"
QQ_SEND_MESSAGE = "qq.send_message"
QQ_SEND_PRIVATE_MESSAGE = "qq.send_private_message"
QQ_REPLY_MESSAGE = "qq.reply_message"
QQ_SEND_FACE = "qq.send_face"
QQ_EXTEND_GROUP_ATTENTION = "qq.extend_group_attention"
QQ_SET_GROUP_CARD = "qq.set_group_card"
QQ_SET_GROUP_BAN = "qq.set_group_ban"
QQ_DELETE_MSG = "qq.delete_msg"
QQ_GET_GROUP_MEMBER_INFO = "qq.get_group_member_info"
QQ_GET_GROUP_MEMBER_LIST = "qq.get_group_member_list"
QQ_GET_GROUP_INFO = "qq.get_group_info"
GITHUB_LIST_PRS = "github.list_prs"
GITHUB_GET_PR = "github.get_pr"
GITHUB_GET_ISSUE = "github.get_issue"
GITHUB_WORKFLOW_STATUS = "github.get_workflow_status"


QQ_CHAT_TOOLS = [
    ONEBOT_CALL,
    QQ_SEND_MESSAGE,
    QQ_REPLY_MESSAGE,
    QQ_SEND_FACE,
    QQ_EXTEND_GROUP_ATTENTION,
]

QQ_GROUP_READ_TOOLS = [
    QQ_GET_GROUP_INFO,
    QQ_GET_GROUP_MEMBER_INFO,
    QQ_GET_GROUP_MEMBER_LIST,
]

QQ_GROUP_ADMIN_TOOLS = [
    QQ_SET_GROUP_CARD,
    QQ_SET_GROUP_BAN,
    QQ_DELETE_MSG,
]

GITHUB_READ_TOOLS = [
    GITHUB_LIST_PRS,
    GITHUB_GET_PR,
    GITHUB_GET_ISSUE,
    GITHUB_WORKFLOW_STATUS,
]


GROUP_IMMEDIATE_TOOLS = [
    *QQ_CHAT_TOOLS,
    *QQ_GROUP_READ_TOOLS,
    *QQ_GROUP_ADMIN_TOOLS,
    *GITHUB_READ_TOOLS,
]

GROUP_AMBIENT_TOOLS = [
    *QQ_CHAT_TOOLS,
    *QQ_GROUP_READ_TOOLS,
    *QQ_GROUP_ADMIN_TOOLS,
    *GITHUB_READ_TOOLS,
]

PRIVATE_TOOLS = [
    QQ_SEND_PRIVATE_MESSAGE,
    *GITHUB_READ_TOOLS,
]


ONEBOT_CHAT_ACTIONS = {
    "send_msg",
    "send_group_msg",
}

ONEBOT_GROUP_READ_ACTIONS = {
    "get_group_info",
    "get_group_member_info",
    "get_group_member_list",
    "get_group_honor_info",
}

ONEBOT_GROUP_ADMIN_ACTIONS = {
    "delete_msg",
    "set_group_card",
    "set_group_ban",
    "set_group_kick",
    "set_group_admin",
    "set_group_whole_ban",
    "set_group_special_title",
}

ONEBOT_ACTION_LEVELS = {
    "chat": ONEBOT_CHAT_ACTIONS,
    "group_read": ONEBOT_CHAT_ACTIONS | ONEBOT_GROUP_READ_ACTIONS,
    "group_admin": ONEBOT_CHAT_ACTIONS | ONEBOT_GROUP_READ_ACTIONS | ONEBOT_GROUP_ADMIN_ACTIONS,
    "full": None,
}


def onebot_actions_for_level(level: str) -> set[str] | None:
    return ONEBOT_ACTION_LEVELS.get(level, ONEBOT_ACTION_LEVELS["group_admin"])
