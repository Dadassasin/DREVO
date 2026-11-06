import { createContext, useContext, useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

export type Role = 'admin' | 'researcher' | 'viewer';
export type Crop = {x: number; y: number; width: number; height: number; output_max_width?: number};
export type Source = { page_id: string; crop?: Crop; sha256?: string };
export type Entity = { id: string; kind: string; title: string; data: Record<string, any>; status: string; version: number; author: string; updated: number; living: boolean; history?: any[] };
export type ArchiveCase = { id: string; title: string; fond?: string; inventory?: string; number?: string; publication: string; metadata_status: string; page_count?: number; metadata_json: Record<string, any> };
export type Page = { id: string; case_id: string; filename: string; jpg_number: string; book_page?: string; archival_leaf?: string; section?: string; sha256: string; width: number; height: number; format: string };
export const apiBase = (import.meta.env.VITE_API_URL || (location.port === '5173' ? 'http://127.0.0.1:8000' : location.origin)).replace(/\/$/, '');
if (location.protocol === 'https:' && !apiBase.startsWith('https://')) throw new Error('Для опубликованного сайта необходим HTTPS API');
type Session = {token: string; role: Role};
type AuthContext = { session: Session | null; setSession: (session: Session | null) => void; request: <T = any>(path: string, options?: RequestInit) => Promise<T>; blob: (path: string, options?: RequestInit) => Promise<Blob> };
const Context = createContext<AuthContext>(null!);
export function AuthProvider({children}: {children: ReactNode}) {
  const [session, setSession] = useState<Session | null>(null);
  const perform = useCallback(async (path: string, options: RequestInit = {}) => {
    const response = await fetch(apiBase + path, {...options, headers: { ...(session ? {Authorization: 'Bearer ' + session.token} : {}), ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers }});
    if (!response.ok) {
      const error = await response.json().catch(() => ({detail: 'Сервер недоступен'}));
      if (response.status === 401 && session) setSession(null);
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Проверьте заполнение полей');
    }
    return response;
  }, [session]);
  const request = useCallback(async <T,>(path: string, options?: RequestInit): Promise<T> => (await perform(path, options)).json(), [perform]);
  const blob = useCallback(async (path: string, options?: RequestInit) => (await perform(path, options)).blob(), [perform]);
  return <Context value={{session, setSession, request, blob}}>{children}</Context>;
}
export const useAuth = () => useContext(Context);
export function useApi<T = any>(path: string, interval?: number, enabled=true) {
  const {request} = useAuth();
  return useQuery<T>({queryKey: [path], queryFn: () => request<T>(path), refetchInterval: interval, retry: 1, enabled});
}
export const post = (body: unknown): RequestInit => ({method:'POST',body:JSON.stringify(body)});
export const statusLabel: Record<string, string> = {proposed:'Предложено', needs_review:'Нужна проверка', human_reviewed:'Проверено человеком', confirmed:'Подтверждено', rejected:'Отклонено', conflicted:'Конфликт версий'};
export const kindLabel: Record<string,string> = {person:'Персона', person_mention:'Упоминание', record:'Историческая запись', claim:'Утверждение', evidence:'Доказательство', transcription:'Транскрипция', relationship:'Родственная связь', research_task:'Исследование', finding:'Находка', annotation:'Аннотация'};
