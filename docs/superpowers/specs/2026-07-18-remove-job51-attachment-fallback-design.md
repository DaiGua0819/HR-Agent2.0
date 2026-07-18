# 删除 51 在线简历附件兜底发送

## 目标

保留 51 在线简历和原生“求简历”按钮的获取尝试，但当在线简历无法导出且原生请求按钮不可用时，不再自动发送“在线简历暂时无法导出，方便发一份附件简历过来吗”或任何替代话术。

## 行为

- 在线简历可导出：继续下载并保存。
- 在线简历不可导出、原生求简历按钮可用：继续点击原生按钮。
- 在线简历不可导出、原生求简历按钮不可用：返回未处理失败状态，不发送文字消息。
- Runner 将该结果归类为 `next_action=request_resume_failed`、`stage=request_resume_action_failed`，使实时处理按异常策略停止，而不是静默继续。
- 新招呼页面也不得把该兜底文案转换成通用求简历话术发送。

## 修改范围

- `app/platforms/job51/actions_resume.py`：删除文字兜底常量和 `needsAttachmentRequest`/`attachmentRequestMessage` 返回值。
- `app/agent/runner.py`：删除通用的附件文字兜底发送分支。
- `tests/agent/test_job51_phase3.py`：改为断言无消息发送且进入失败阶段。

## 验收

- 线上简历无导出控件、无原生请求按钮时，`page.sent_messages == []`。
- 状态为 `next_action=request_resume_failed`、`stage=request_resume_action_failed`，失败原因保留 `online_resume_not_exportable_attachment_request_unavailable`。
- 在线简历正常下载和原生求简历按钮行为不变。
