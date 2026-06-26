"""智联 DOM 选择器沉淀文件。

选择器来自智联 skill 与旧 `agent_web_server.part006/part007`，这里只放纯数据。
"""

from __future__ import annotations

CHAT_URL = "https://rd6.zhaopin.com/app/im"
RECOMMEND_URL = "https://rd6.zhaopin.com/app/recommend"

UNREAD_FILTER = (
    ".side-panel-header__checkbox, .km-checkbox, [role='checkbox'], "
    "label, button,a,span,div,[role='button']"
)
POSITION_FILTER = ".app-job-selector, .im-job-filter, [class*='job-filter']"
ALL_POSITION_OPTION_TEXT = "全部职位"

SESSION_ITEM = ".im-session-item__box"
SESSION_NAME = ".im-session-item__name-title"
SESSION_POSITION = ".im-session-item-subtitle__suffix"
SESSION_MESSAGE = ".im-session-item__msg"
SESSION_UNREAD = ".im-session-item__unread"
SESSION_LIST = ".im-session-list__virtual, .im-session-list, [class*='im-session-list']"

CHAT_READY = ".im-sender__input textarea, textarea[placeholder*='从这里开启对话']"
CHAT_INPUT = (
    ".im-sender__input textarea, .im-sender textarea, "
    "textarea[placeholder*='从这里开启对话'], textarea"
)
MESSAGE_ITEM = ".km-list__item.im-message, .im-message"
MESSAGE_TEXT = ".im-message__text, .im-message__bubble-inner, .im-message__toast-inner"
MINE_MESSAGE = "div.message-item.mine, .im-message__bubble--me, [class*='mine'], [class*='myself']"

REQUEST_RESUME_BUTTON = (
    ".im-ask-for-wx, .newest-attach-resume, "
    ".hover-resume-footer__button--attachment, a,button,[role='button'],span,div"
)
REQUEST_RESUME_TEXT = "要附件简历"
REQUEST_RESUME_CONFIRM_BUTTON = (
    ".km-modal--open button, .km-dialog button, "
    ".im-dialog button, button, [role='button']"
)
REQUEST_RESUME_CONFIRM_TEXTS = ("确定", "确认", "发送")
ATTACHMENT_VIEW_TEXT = "查看附件简历"

RECOMMEND_POSITION_ITEM = ".job-pane__item"
RECOMMEND_POSITION_EXTRA = ".job-pane__extra"
RECOMMEND_SIDE_POSITION_ITEM = ".job-side-selector__item"
RECOMMEND_CARD = ".recommend-item.recommend-resume-item, .recommend-resume-item"
RECOMMEND_MODAL = ".new-shortcut-resume__modal .km-modal--open, .new-shortcut-resume__modal"
RECOMMEND_MODAL_CLOSE = (
    ".new-shortcut-resume__modal .new-shortcut-resume__close, "
    ".new-shortcut-resume__close, .km-modal--open .km-modal__close, .km-modal__close"
)
RECOMMEND_MODAL_LEFT = ".new-shortcut-resume__left"
RECOMMEND_MODAL_RIGHT = ".new-shortcut-resume__right"
RECOMMEND_GREET_BUTTON_TEXT = "打招呼"
RECOMMEND_PHONE_TEXT = "打电话"

ZHILIAN_SELECTORS: dict[str, str] = {
    "chat_url": CHAT_URL,
    "recommend_url": RECOMMEND_URL,
    "unread_filter": UNREAD_FILTER,
    "position_filter": POSITION_FILTER,
    "session_item": SESSION_ITEM,
    "chat_input": CHAT_INPUT,
    "message_item": MESSAGE_ITEM,
    "mine_message": MINE_MESSAGE,
    "request_resume_button": REQUEST_RESUME_BUTTON,
    "recommend_card": RECOMMEND_CARD,
    "recommend_modal": RECOMMEND_MODAL,
    "recommend_modal_close": RECOMMEND_MODAL_CLOSE,
}
