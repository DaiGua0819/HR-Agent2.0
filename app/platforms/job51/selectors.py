"""51job DOM 选择器沉淀文件。

选择器来自 `51job-recruiter-automation/SKILL.md` 与旧 `job51_*` 方法。
本文件只存纯数据，不承载业务判断。
"""

from __future__ import annotations

CHAT_HOME_URL = "https://ehire.51job.com/Revision/chat"
CHAT_ENTRY = "#sensor_talentcommunicate"
POSITION_MENU = ".position-menu .menu-item"
POSITION_MENU_SHORT = ".menu-item_content_short"
ALL_POSITION_MENU = ".menu-item-all"
UNREAD_FILTER = "label.el-checkbox.btn.unread-checkbox"
THREAD_ITEM = "#conversation-list .list-item"
THREAD_JOB_NAME = ".jobname"

CANDIDATE_NAME = "div.im_userName span.username-text, div.im_userName"
MESSAGE_ITEM = "div.im-message-item, div.message-item.others, div.message-item.mine"
CHAT_INPUT = "#drop-area.input-textarea_self"
SEND_BUTTON = "button.el-button.new-send-button.el-button--primary"
MINE_MESSAGE = "div.message-item.mine"

NEW_GREETING_BATCH_REPLY_BUTTON = "#sensor_Bchat_plbatchreply"
NEW_GREETING_PHRASE_ITEM = (
    ".el-popover:visible .greeting-item.greeting-item-batch"
)
NEW_GREETING_SEND_BUTTON = (
    ".el-popover:visible .greeting-btn button.el-button--primary"
)

AI_GUIDE_CLOSE = "button.ai-guide-btn-no"
WECHAT_NOTIFY_CLOSE = ".wechat-notify .close, .wechat-notify .el-icon-close"
INTERRUPTION_CLOSE_TEXTS = ("不感兴趣", "跳过", "稍后再说", "知道了", "我知道了")

REQUEST_RESUME_BUTTON = "div.operate-item, button, [role='button']"
REQUEST_RESUME_TEXT = "求简历"
REQUEST_RESUME_CONFIRM_BUTTON = (
    ".el-message-box__btns button.el-button--primary, "
    ".el-dialog__footer button.el-button--primary, "
    "button.el-button--primary, button, [role='button']"
)
REQUEST_RESUME_CONFIRM_TEXTS = ("确定", "确认", "发送")
RESUME_CARD = "div.item.resume-card"
ONLINE_RESUME_ENTRY = "div.item.resume-card, div.im-message-item .resume-card"
ATTACHMENT_ENTRY = "a[href], div.im-message-item a[href]"
ATTACHMENT_RESUME_BUTTON = ".resume-element .info-content-item.file-item"
ONLINE_RESUME_BUTTON_TEXT = "在线简历"
ANNEX_DOWNLOAD_LINK = ".annex-resume #sensor_Bchatinfo_xiazai a, .annex-resume .item-download a"
ANNEX_CLOSE = ".annex-resume .container-close"

RECOMMEND_ENTRY = "#sensor_recommand_menu"
RECOMMEND_CARD = "div.item.resume-card, .resume-card"
RECOMMEND_GREET_BUTTON = "button.el-button.tm_button.el-button--primary"
RECOMMEND_GREET_TEXT = "立即Hi聊"
RECOMMEND_MODE_SWITCH = ".ai-mode-switch"
RECOMMEND_MODE_SWITCH_ACTIVE = ".ai-mode-switch.ai-mode-switch-active"
RECOMMEND_POSITION_TAB = ".position-menu .menu-item, .job-tabs .tab-item"

BATCH_PANEL = "section.batch-chat-panel"
BATCH_WRAP_ITEM = ".wrap-item, .batch-chat-item"

JOB51_SELECTORS: dict[str, str] = {
    "chatEntry": CHAT_ENTRY,
    "positionMenu": POSITION_MENU,
    "unreadFilter": UNREAD_FILTER,
    "threadItem": THREAD_ITEM,
    "chatInput": CHAT_INPUT,
    "sendButton": SEND_BUTTON,
    "mineMessage": MINE_MESSAGE,
    "recommendEntry": RECOMMEND_ENTRY,
    "recommendCard": RECOMMEND_CARD,
    "recommendGreetButton": RECOMMEND_GREET_BUTTON,
    "recommendModeSwitch": RECOMMEND_MODE_SWITCH,
}
