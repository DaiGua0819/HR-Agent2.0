"""面试反馈回填。

对应旧 `feedbackBackfill.js`：把面试结果/反馈写回会话并同步到飞书。Phase 6 只写内存
和 mock bitable。
"""

from __future__ import annotations

from typing import Any

from app.features.interview_center.feishu.assets import BITABLE_TABLES, FeedbackFields
from app.features.interview_center.feishu.bitable import BitableClientProtocol
from app.features.interview_center.store import InterviewStoreProtocol


class FeedbackBackfillService:
    """反馈回填服务。"""

    def __init__(
        self,
        *,
        store: InterviewStoreProtocol,
        bitable: BitableClientProtocol,
        feedback_table_id: str = BITABLE_TABLES.feedback,
    ) -> None:
        self.store = store
        self.bitable = bitable
        self.feedback_table_id = feedback_table_id

    async def backfill(
        self,
        session_id: str,
        *,
        result: str,
        feedback: str,
        interviewer: str = "",
    ) -> dict[str, Any]:
        """回填一条面试反馈。"""

        session = self.store.get(session_id)
        if session is None:
            raise KeyError("interview_session_not_found")
        session.feedback = feedback
        session.status = result or "feedback_received"
        self.store.save(session)
        fields = {
            FeedbackFields.SESSION_ID: session_id,
            FeedbackFields.RESULT: result,
            FeedbackFields.FEEDBACK: feedback,
            FeedbackFields.INTERVIEWER: interviewer,
        }
        record = await self.bitable.create_record(self.feedback_table_id, fields)
        return {"session": session.to_dict(), "feedbackRecord": record}
