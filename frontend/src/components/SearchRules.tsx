import {useEffect,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {useApi,useAuth} from '../api';
import {Button} from './ui/button';

type Rule={source:string;target:string};
export default function SearchRules(){
  const {data}=useApi<{rules:Rule[]}>('/api/search-rules');const {request}=useAuth();const cache=useQueryClient();
  const [rules,setRules]=useState<Rule[]>([]);const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [saved,setSaved]=useState(false);
  useEffect(()=>{if(data)setRules(data.rules);},[data]);
  return <section className="panel editor"><h2>Правила сравнения при поиске</h2><p className="muted">Замены применяются только к поисковому индексу. Исходный текст сохраняется, люди автоматически не объединяются.</p>{rules.map((rule,i)=><div className="inline-fields" key={i}><label>Искать как<input value={rule.source} maxLength={30} onChange={e=>setRules(rules.map((r,n)=>n===i?{...r,source:e.target.value}:r))}/></label><label>Считать эквивалентным<input value={rule.target} maxLength={30} onChange={e=>setRules(rules.map((r,n)=>n===i?{...r,target:e.target.value}:r))}/></label><Button variant="ghost" type="button" onClick={()=>setRules(rules.filter((_,n)=>n!==i))}>Удалить правило</Button></div>)}<div className="actions"><Button variant="outline" onClick={()=>setRules([...rules,{source:'',target:''}])}>Добавить правило</Button><Button disabled={busy||rules.some(r=>!r.source)} onClick={async()=>{setBusy(true);setError('');setSaved(false);try{await request('/api/search-rules',{method:'PATCH',body:JSON.stringify({rules})});await cache.invalidateQueries();setSaved(true);}catch(e){setError(String(e));}finally{setBusy(false);}}}>{busy?'Обновляем индекс…':'Сохранить и обновить поиск'}</Button></div>{error&&<p className="error" role="alert">{error}</p>}{saved&&<p role="status">Правила сохранены, индекс обновлён.</p>}</section>;
}
