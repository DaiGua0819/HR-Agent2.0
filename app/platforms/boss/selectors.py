"""BOSS DOM 选择器沉淀文件。

选择器来自 `boss-recruiter-automation/SKILL.md` 与旧
`agent_web_server.part012/part013/part014/part018.py` 的 BOSS recruiter
流程描述。这里只放纯数据，页面语义由 actions 解释。
"""

from __future__ import annotations

CHAT_URL = "https://www.zhipin.com/web/chat/index"
RECOMMEND_URL = "https://www.zhipin.com/web/chat/recommend"

UNREAD_FILTER = ".chat-message-filter-left, .chat-message-filter-left *, .chat-message-filter"
POSITION_FILTER = (
    ".chat-top-job, .chat-select-job, .chat-job, "
    ".job-selecter-wrap .ui-dropmenu-label"
)
ALL_POSITION_OPTION_TEXT = "全部职位"

SESSION_ITEM = (
    ".user-list .geek-item, .chat-user-list .user-list-item, "
    ".chat-list .user-item, .user-list-item"
)
MESSAGE_ITEM = (
    ".conversation-message .message-item, .chat-message-list .message-item, .message-item"
)
CHAT_INPUT = (
    "#boss-chat-editor-input, .conversation-editor [contenteditable='true'], "
    ".conversation-editor textarea, textarea, [contenteditable='true']"
)
SEND_BUTTON = (
    ".conversation-editor .submit, .conversation-editor .submit-content, "
    ".btn-send, button[class*='send'], [class*='send']"
)
MINE_MESSAGE = (
    ".conversation-message .item-myself, .chat-message-list .item-myself, "
    ".message-item.mine, .chat-message.mine, .item-myself"
)

REQUEST_RESUME_BUTTON = (
    ".resume-btn-online, .resume-btn-file, .toolbar-box-right .operate-btn, "
    ".conversation-operate .operate-btn, button, [role='button'], "
    ".toolbar button, .chat-op button, .btn-request-resume"
)
REQUEST_RESUME_TEXT = "求简历"
UNSUITABLE_BUTTON_TEXT = "不合适"

COMMON_PHRASE_BUTTON = "button, [role='button'], .common-phrase, .phrase-entry"
COMMON_PHRASE_PANEL = ".common-phrase-panel, .quick-reply-panel, .phrase-list"
COMMON_PHRASE_SEND = f"{COMMON_PHRASE_PANEL} button, {COMMON_PHRASE_PANEL} [role='button']"
COMMON_PHRASE_TEXT = "常用语"

RECOMMEND_POSITION_LABEL = ".job-selecter-wrap .ui-dropmenu-label"
RECOMMEND_CARD = ".candidate-card-wrap"
RECOMMEND_DIALOG = ".dialog-wrap.active"
RECOMMEND_GREET_BUTTON = ".dialog-wrap.active button.btn-greet"
RECOMMEND_GREET_BUTTON_TEXT = "打招呼"
RECOMMEND_SIMILAR_BLOCK = ".similar-geek-wrap,.similar-geek-list,.similar-card-wrap"
RECOMMEND_DIALOG_CLOSE = ".dialog-wrap.active .close-btn, .dialog-wrap.active .boss-dialog-close"
RECOMMEND_RESUME_TEXT = (
    ".dialog-wrap.active .resume-left-side, .dialog-wrap.active .resume-content, "
    ".dialog-wrap.active .resume-detail, .dialog-wrap.active .resume-preview, "
    ".dialog-wrap.active"
)

BOSS_SELECTORS: dict[str, str] = {
    "chatUrl": CHAT_URL,
    "recommendUrl": RECOMMEND_URL,
    "unreadFilter": UNREAD_FILTER,
    "positionFilter": POSITION_FILTER,
    "sessionItem": SESSION_ITEM,
    "messageItem": MESSAGE_ITEM,
    "chatInput": CHAT_INPUT,
    "sendButton": SEND_BUTTON,
    "requestResumeButton": REQUEST_RESUME_BUTTON,
    "recommendPositionLabel": RECOMMEND_POSITION_LABEL,
    "recommendCard": RECOMMEND_CARD,
    "recommendDialog": RECOMMEND_DIALOG,
    "recommendGreetButton": RECOMMEND_GREET_BUTTON,
    "recommendSimilarBlock": RECOMMEND_SIMILAR_BLOCK,
}
