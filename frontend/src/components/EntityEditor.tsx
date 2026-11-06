import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth, useApi, post, kindLabel } from '../api';
import type { Entity, Source, Page, ArchiveCase } from '../api';
import { Button } from './ui/button';

type Props = {defaultKind?:string; source?:Source; onSaved:()=>void; initial?:Entity};
export function EntityEditor({defaultKind='finding', source, onSaved, initial}:Props) {
  const {request}=useAuth();const cache=useQueryClient();
  const [kind,setKind]=useState(initial?.kind||defaultKind);
  const [title,setTitle]=useState(initial?.title||'');
  const [text,setText]=useState(initial?.data.text||'');
  const [normalized,setNormalized]=useState(initial?.data.normalized||'');
  const [note,setNote]=useState(initial?.data.source_note||'');
  const [uncertain,setUncertain]=useState(initial?.data.uncertain||false);
  const [alternatives,setAlternatives]=useState((initial?.data.alternatives||[]).join('\n'));
  const [confidence,setConfidence]=useState(initial?.data.confidence||'unknown');
  const [living,setLiving]=useState(initial?.living||false);
  const [advanced,setAdvanced]=useState('');
  const [error,setError]=useState<unknown>();const [busy,setBusy]=useState(false);
  const [caseId,setCaseId]=useState('');const [pageId,setPageId]=useState('');
  const [person,setPerson]=useState(initial?.data.person_id||'');
  const [record,setRecord]=useState(initial?.data.record_id||'');
  const [claim,setClaim]=useState(initial?.data.claim_id||'');
  const [from,setFrom]=useState(initial?.data.from_person_id||'');
  const [to,setTo]=useState(initial?.data.to_person_id||'');
  const [relation,setRelation]=useState(initial?.data.relationship_type||'parent');
  const [evidence,setEvidence]=useState<string[]>(initial?.data.evidence_ids||[]);
  const [supports,setSupports]=useState(initial?.data.supports!==false);
  const [place,setPlace]=useState(initial?.data.place||'');
  const [eventType,setEventType]=useState(initial?.data.event_type||'birth');
  const [recordNumber,setRecordNumber]=useState(initial?.data.record_number||'');
  const [originalDate,setOriginalDate]=useState(initial?.data.dates?.[0]?.original||'');
  const [calendar,setCalendar]=useState(initial?.data.dates?.[0]?.calendar||'unknown');
  const [year,setYear]=useState(String(initial?.data.dates?.[0]?.year||''));
  const [month,setMonth]=useState(String(initial?.data.dates?.[0]?.month||''));
  const [day,setDay]=useState(String(initial?.data.dates?.[0]?.day||''));
  const [approximate,setApproximate]=useState(initial?.data.dates?.[0]?.approximate||false);
  const [goal,setGoal]=useState(initial?.data.goal||'');
  const [facts,setFacts]=useState((initial?.data.facts||[]).join('\n'));
  const [assumptions,setAssumptions]=useState((initial?.data.assumptions||[]).join('\n'));
  const [nextAction,setNextAction]=useState(initial?.data.next_action||'');
  const {data:cases}=useApi<{items:ArchiveCase[]}>('/api/cases?limit=200');
  const {data:pages}=useApi<{items:Page[]}>(`/api/cases/${caseId}/pages?limit=200`,undefined,!!caseId);
  const {data:people}=useApi<Entity[]>('/api/entities?kind=person&limit=200',undefined,['relationship','person_mention'].includes(kind));
  const {data:records}=useApi<Entity[]>('/api/entities?kind=record&limit=200',undefined,kind==='person_mention');
  const {data:claims}=useApi<Entity[]>('/api/entities?kind=claim&limit=200',undefined,kind==='evidence');
  const {data:evidences}=useApi<Entity[]>('/api/entities?kind=evidence&limit=200',undefined,kind==='relationship');
  const lines=(value:string)=>value.split('\n').map(x=>x.trim()).filter(Boolean);
  const personSelect=(label:string,value:string,change:(value:string)=>void)=><label>{label}<select required value={value} onChange={e=>change(e.target.value)}><option value="">Выберите персону</option>{people?.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label>;

  async function submit(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError(undefined);
    try {
      const data:Record<string,any>={...initial?.data,text,normalized,source_note:note,uncertain,confidence,alternatives:lines(alternatives)};
      delete data.demo;
      if(source)data.sources=[source];else if(pageId)data.sources=[{page_id:pageId}];
      if(kind==='record'){data.event_type=eventType;data.record_number=recordNumber;data.place=place;}
      if(kind==='person_mention'){data.person_id=person||null;data.record_id=record||null;}
      if(kind==='evidence'){data.claim_id=claim||null;data.supports=supports;}
      if(kind==='relationship'){data.from_person_id=from;data.to_person_id=to;data.relationship_type=relation;data.evidence_ids=evidence;}
      if(kind==='research_task'){data.goal=goal||title;data.facts=lines(facts);data.assumptions=lines(assumptions);data.next_action=nextAction;if(caseId)data.case_ids=[caseId];}
      if(originalDate)data.dates=[{original:originalDate,calendar,approximate,...(year?{year:+year}:{}),...(month?{month:+month}:{}),...(day?{day:+day}:{})},...(initial?.data.dates?.slice(1)||[])];
      if(advanced)Object.assign(data,JSON.parse(advanced));
      await request('/api/entities',post({kind,title,data,living}));
      await cache.invalidateQueries();onSaved();
    } catch(e){setError(e);}finally{setBusy(false);}
  }
  return <form className="panel editor" onSubmit={submit}>
    <h2>{initial?'Создать исправленный вариант':'Новая запись'}</h2>
    <div className="inline-fields"><label>Тип<select value={kind} onChange={e=>setKind(e.target.value)}>{Object.entries(kindLabel).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><label className="grow">Название<input required maxLength={500} value={title} onChange={e=>setTitle(e.target.value)}/></label></div>
    {!source&&<details open={['record','transcription','person_mention','evidence','annotation'].includes(kind)}><summary>Архивный источник</summary><label>Дело<select value={caseId} onChange={e=>{setCaseId(e.target.value);setPageId('');}}><option value="">Выберите дело</option>{cases?.items.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label>{caseId&&<label>Страница<select value={pageId} onChange={e=>setPageId(e.target.value)}><option value="">Выберите JPG</option>{pages?.items.map(p=><option key={p.id} value={p.id}>JPG {p.jpg_number}{p.archival_leaf?' · л. '+p.archival_leaf:''}</option>)}</select></label>}<label>ID страницы (если её нет в списке)<input value={pageId} onChange={e=>setPageId(e.target.value)} placeholder="Скопируйте ID во вкладке «Источник» просмотрщика"/></label><p className="muted">Для вырезки откройте страницу в архиве, выделите запись и создайте транскрипцию оттуда.</p></details>}
    {source&&<p className="source-caption">Источник: страница {source.page_id.slice(0,8)}{source.crop?`, вырезка ${source.crop.x}, ${source.crop.y}, ${source.crop.width} × ${source.crop.height}`:', целая страница'}</p>}
    {kind==='relationship'&&<><div className="inline-fields">{personSelect('Первая персона',from,setFrom)}{personSelect('Вторая персона',to,setTo)}</div><label>Связь<select value={relation} onChange={e=>setRelation(e.target.value)}><option value="parent">Первая персона — родитель второй</option><option value="spouse">Супруги</option><option value="sibling">Брат / сестра</option><option value="other">Другая связь</option></select></label><label>Доказательства (можно несколько)<select multiple size={4} value={evidence} onChange={e=>setEvidence(Array.from(e.target.selectedOptions,o=>o.value))}>{evidences?.map(e=><option key={e.id} value={e.id}>{e.title} · {e.status==='confirmed'?'подтверждено':'не подтверждено'}</option>)}</select></label><p className="muted">Сначала сохранится гипотеза. Подтверждение родства требует проверенных доказательств.</p></>}
    {kind==='person_mention'&&<div className="inline-fields">{personSelect('Связанная персона',person,setPerson)}<label>Историческая запись<select value={record} onChange={e=>setRecord(e.target.value)}><option value="">Не привязана</option>{records?.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label></div>}
    {kind==='evidence'&&<><label>Проверяемое утверждение<select value={claim} onChange={e=>setClaim(e.target.value)}><option value="">Выберите утверждение</option>{claims?.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label><label className="check"><input type="checkbox" checked={supports} onChange={e=>setSupports(e.target.checked)}/>Подтверждает утверждение (снимите, если опровергает)</label></>}
    {kind==='record'&&<><div className="inline-fields"><label>Событие<select value={eventType} onChange={e=>setEventType(e.target.value)}><option value="birth">Рождение</option><option value="baptism">Крещение</option><option value="marriage">Брак</option><option value="death">Смерть</option><option value="other">Другое</option></select></label><label>Номер записи<input value={recordNumber} onChange={e=>setRecordNumber(e.target.value)}/></label></div><label>Населённый пункт<input value={place} onChange={e=>setPlace(e.target.value)}/></label></>}
    {kind==='research_task'&&<><label>Цель<textarea value={goal} onChange={e=>setGoal(e.target.value)} rows={2}/></label><label>Известные факты (по одному на строке)<textarea value={facts} onChange={e=>setFacts(e.target.value)} rows={3}/></label><label>Предположения (по одному на строке)<textarea value={assumptions} onChange={e=>setAssumptions(e.target.value)} rows={3}/></label><label>Следующее действие<textarea value={nextAction} onChange={e=>setNextAction(e.target.value)} rows={2}/></label></>}
    <label>{kind==='transcription'?'Дословная транскрипция':'Описание'}<textarea value={text} onChange={e=>setText(e.target.value)} rows={5} placeholder="Сохраняйте оригинальное написание; гипотезы отмечайте отдельно."/></label>
    {kind==='transcription'&&<><label>Нормализованный вариант<textarea value={normalized} onChange={e=>setNormalized(e.target.value)} rows={2}/></label><label>Альтернативные прочтения (по одному на строке)<textarea value={alternatives} onChange={e=>setAlternatives(e.target.value)} rows={2}/></label><label>Уверенность<select value={confidence} onChange={e=>setConfidence(e.target.value)}><option value="unknown">Не оценена</option><option value="low">Низкая</option><option value="medium">Средняя</option><option value="high">Высокая</option></select></label></>}
    {['record','person','finding','claim'].includes(kind)&&<details><summary>Дата и календарный стиль</summary><label>Дата как в источнике<input value={originalDate} onChange={e=>setOriginalDate(e.target.value)}/></label><label>Календарь<select value={calendar} onChange={e=>setCalendar(e.target.value)}><option value="unknown">Не установлен</option><option value="julian">Юлианский</option><option value="gregorian">Григорианский</option></select></label><div className="inline-fields"><label>Год<input type="number" min="1" max="2200" value={year} onChange={e=>setYear(e.target.value)}/></label><label>Месяц<input type="number" min="1" max="12" value={month} onChange={e=>setMonth(e.target.value)}/></label><label>День<input type="number" min="1" max="31" value={day} onChange={e=>setDay(e.target.value)}/></label></div><label className="check"><input type="checkbox" checked={approximate} onChange={e=>setApproximate(e.target.checked)}/>Приблизительная дата</label></details>}
    <label>Примечание об источнике<textarea value={note} onChange={e=>setNote(e.target.value)} rows={2}/></label>
    <label className="check"><input type="checkbox" checked={uncertain} onChange={e=>setUncertain(e.target.checked)}/>Есть неуверенное прочтение (необходима вырезка)</label>
    <label className="check"><input type="checkbox" checked={living} onChange={e=>setLiving(e.target.checked)}/>Сведения о живом человеке — не экспортировать в GitHub</label>
    <details><summary>Дополнительные структурированные поля</summary><p className="muted">Для расширенных сценариев: JSON по EntityData, включая просмотренные и полностью изученные страницы. Перечисляйте их отдельно.</p><textarea aria-label="Дополнительные поля JSON" className="mono" value={advanced} onChange={e=>setAdvanced(e.target.value)} rows={5}/></details>
    {!!error&&<div className="error" role="alert">{error instanceof Error?error.message:String(error)}</div>}
    <div className="actions"><Button type="submit" disabled={busy}>{busy?'Сохраняем…':'Сохранить предложение'}</Button><Button type="button" variant="ghost" onClick={onSaved}>Закрыть</Button></div>
  </form>;
}
