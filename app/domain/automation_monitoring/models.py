"""Normalized automation monitoring models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MonitoringModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AutomationContactEvent(MonitoringModel):
    id: str
    contact_key: str = Field(alias="contactKey")
    owner: str
    platform: str
    candidate_name: str = Field(default="", alias="candidateName")
    job_type: str = Field(default="", alias="jobType")
    occurred_at: str = Field(alias="occurredAt")
    action: str = ""
    stage: str = ""
    processed: bool = True
    sent_company_info: bool = Field(default=False, alias="sentCompanyInfo")
    requested_resume: bool = Field(default=False, alias="requestedResume")
    candidate_question: bool = Field(default=False, alias="candidateQuestion")
    knowledge_answered: bool = Field(default=False, alias="knowledgeAnswered")
    resume_acquired: bool = Field(default=False, alias="resumeAcquired")
    resume_handling: str = Field(default="", alias="resumeHandling")
    resume_file_hash: str = Field(default="", alias="resumeFileHash")
    anomaly: bool = False
    anomaly_reason: str = Field(default="", alias="anomalyReason")
    payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(alias="updatedAt")


class AutomationRuntimeStatus(MonitoringModel):
    target_key: str = Field(alias="targetKey")
    owner: str
    platform: str
    status: str
    agent_ready: bool = Field(default=False, alias="agentReady")
    browser_ready: bool = Field(default=False, alias="browserReady")
    cdp_ready: bool = Field(default=False, alias="cdpReady")
    agent_busy: bool = Field(default=False, alias="agentBusy")
    authenticated: bool = False
    needs_login: bool = Field(default=False, alias="needsLogin")
    security_verification: bool = Field(default=False, alias="securityVerification")
    account_abnormal: bool = Field(default=False, alias="accountAbnormal")
    page_present: bool = Field(default=False, alias="pagePresent")
    paused: bool = False
    reason: str = ""
    checked_at: str = Field(alias="checkedAt")
    received_at: str = Field(alias="receivedAt")
