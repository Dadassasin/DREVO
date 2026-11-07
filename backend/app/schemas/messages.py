from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal['proposed', 'needs_review', 'human_reviewed', 'confirmed', 'rejected', 'conflicted']
Kind = Literal['person', 'person_mention', 'record', 'claim', 'evidence', 'transcription', 'relationship', 'research_task', 'finding', 'annotation', 'hypothesis']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Crop(Strict):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    output_max_width: int = Field(default=2400, ge=64, le=4096)


class PageRequest(Strict):
    schema_version: Literal['1.0'] = '1.0'
    request_id: UUID
    operation: Literal['get_pages', 'get_crop', 'search', 'get_research_context', 'renew_image_links']
    created_by: Literal['chatgpt'] = 'chatgpt'
    status: Literal['pending'] = 'pending'
    case_id: str | None = Field(default=None, max_length=100)
    page_numbers: list[str] = Field(default_factory=list, max_length=20)
    page_id: str | None = Field(default=None, max_length=100)
    variant: Literal['original', 'preview', 'thumbnail'] = 'original'
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    output_max_width: int = Field(default=2400, ge=64, le=4096)
    query: str = Field(default='', max_length=200)
    renew_request_id: UUID | None = None


class Source(Strict):
    page_id: str
    crop: Crop | None = None
    sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class HistoricalDate(Strict):
    original: str = Field(max_length=200)
    calendar: Literal['julian', 'gregorian', 'unknown'] = 'unknown'
    year: int | None = Field(default=None, ge=1, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    approximate: bool = False
    modern_equivalent: str | None = None

    @model_validator(mode='after')
    def unknown_style(self):
        if self.calendar == 'unknown' and self.modern_equivalent:
            raise ValueError('Нельзя вычислить эквивалент при неизвестном календарном стиле')
        if self.day and self.month:
            days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            if self.year and self.calendar != 'unknown':
                leap = self.year % 4 == 0
                if self.calendar == 'gregorian':
                    leap = leap and (self.year % 100 != 0 or self.year % 400 == 0)
                days[1] = 29 if leap else 28
            if self.day > days[self.month - 1]:
                raise ValueError('Недопустимый день для месяца и календаря; сохраните спорное написание в original')
        return self


class EntityData(Strict):
    sources: list[Source] = Field(default_factory=list, max_length=30)
    text: str = Field(default='', max_length=30000)
    normalized: str = Field(default='', max_length=30000)
    alternatives: list[str] = Field(default_factory=list, max_length=30)
    uncertain: bool = False
    confidence: Literal['unknown', 'low', 'medium', 'high'] = 'unknown'
    source_note: str = Field(default='', max_length=5000)
    dates: list[HistoricalDate] = Field(default_factory=list, max_length=20)
    person_id: str | None = None
    record_id: str | None = None
    claim_id: str | None = None
    from_person_id: str | None = None
    to_person_id: str | None = None
    relationship_type: Literal['parent', 'spouse', 'sibling', 'other'] = 'other'
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    supports: bool = True
    event_type: str = Field(default='', max_length=100)
    place: str = Field(default='', max_length=300)
    church: str = Field(default='', max_length=300)
    section: str = Field(default='', max_length=300)
    record_number: str = Field(default='', max_length=50)
    goal: str = Field(default='', max_length=5000)
    facts: list[str] = Field(default_factory=list, max_length=100)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    case_ids: list[str] = Field(default_factory=list, max_length=100)
    viewed_page_ids: list[str] = Field(default_factory=list, max_length=500)
    studied_page_ids: list[str] = Field(default_factory=list, max_length=500)
    candidate_ids: list[str] = Field(default_factory=list, max_length=100)
    rejected_candidate_ids: list[str] = Field(default_factory=list, max_length=100)
    next_action: str = Field(default='', max_length=5000)
    demo: bool = False


class EntityInput(Strict):
    kind: Kind
    title: str = Field(min_length=1, max_length=500)
    data: EntityData
    living: bool = False


class InboxMessage(Strict):
    schema_version: Literal['1.0'] = '1.0'
    operation_id: UUID
    operation: Literal['create_record', 'add_person_mention', 'save_transcription', 'add_evidence', 'propose_relationship', 'create_finding', 'save_research_progress', 'propose_correction', 'create_person', 'create_claim', 'save_annotation', 'create_hypothesis']
    created_by: Literal['chatgpt'] = 'chatgpt'
    title: str = Field(min_length=1, max_length=500)
    data: EntityData
    entity_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    living: bool = False


class ReviewInput(Strict):
    status: Status
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=5000)
    acknowledge_significant: bool = False
    replacement: EntityInput | None = None
