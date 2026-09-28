from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
TextList = Annotated[list[ShortText], Field(max_length=8)]
AgentName = Literal['technical', 'business', 'user']
Phase = Literal['draft', 'feedback', 'revise', 'synthesize']

AGENTS = {
    'technical': {'label': '기술 전문가', 'role': '구현 가능성, 데이터 품질, 연동과 운영 제약'},
    'business': {'label': '비용 전문가', 'role': '비용, 기대 효익, 성과 측정과 도입 범위'},
    'user': {'label': '사용자 전문가', 'role': '현업 사용 흐름, 도입 부담, 사람의 확인 절차'},
}


class ReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    proposal: str = Field(min_length=20, max_length=4000)
    mode: Literal['demo', 'claude'] = 'demo'


class ReviewContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    headline: ShortText
    position: Literal['pilot', 'proceed', 'rework'] = 'pilot'
    findings: TextList = Field(default_factory=list)
    risks: TextList = Field(default_factory=list)
    actions: TextList = Field(default_factory=list)
    metrics: TextList = Field(default_factory=list)
    changes: TextList = Field(default_factory=list)


class AgentJob(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: str = Field(min_length=1, max_length=64)
    phase: Phase
    proposal: str = Field(min_length=1, max_length=4000)
    author: AgentName | None = None
    draft: ReviewContent | None = None
    feedback: dict[AgentName, ReviewContent] = Field(default_factory=dict, max_length=3)

