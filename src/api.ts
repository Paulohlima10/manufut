import type {Room,Team} from './types';

export const shareOrigin=(import.meta.env.VITE_SHARE_HOST||window.location.origin).replace(/\/$/,'');

const apiBase=()=>{
  if(import.meta.env.VITE_API_URL)return import.meta.env.VITE_API_URL.replace(/\/$/,'');
  if(import.meta.env.DEV)return '';
  return `http://${new URL(shareOrigin).hostname}:8002`;
};

export const inviteUrl=(code:string)=>`${shareOrigin}?room=${code}`;
const authHeaders=()=>{const token=localStorage.getItem('token');if(!token)throw new Error('Sessão expirada. Entre novamente.');return {Authorization:`Bearer ${token}`,'Content-Type':'application/json'} as Record<string,string>};
const body=(name:string,team:Team)=>({player_name:name,team_name:team.name,team_short:team.short,primary:team.primary,secondary:team.secondary,player_names:team.players,player_photos:team.playerPhotos});
async function request(path:string,options:RequestInit={}){const controller=new AbortController();const timeout=window.setTimeout(()=>controller.abort(),15000);try{const r=await fetch(`${apiBase()}${path}`,{...options,headers:{...authHeaders(),...options.headers},signal:controller.signal});if(!r.ok){const payload=await r.json().catch(()=>({}));const detail=typeof payload.detail==='string'?payload.detail:'Não foi possível continuar';if(r.status===404&&path.includes('/join'))throw new Error('Sala não encontrada neste servidor. Abra o link de convite do anfitrião (não basta o código).');throw new Error(detail)}return r.json()}finally{window.clearTimeout(timeout)}}
export const createRoom=(name:string,team:Team):Promise<Room>=>request('/api/rooms',{method:'POST',body:JSON.stringify(body(name,team))});
export const joinRoom=(code:string,name:string,team:Team):Promise<Room>=>request(`/api/rooms/${code}/join`,{method:'POST',body:JSON.stringify(body(name,team))});
export const getRoom=(code:string):Promise<Room>=>request(`/api/rooms/${code}`);
export const saveTeam=(name:string,team:Team):Promise<{player_photos:string[]}>=>request('/api/team',{method:'PUT',body:JSON.stringify(body(name,team))});
export const getHistory=():Promise<Room[]>=>request('/api/history');
export const wsUrl=(code:string)=>{const base=apiBase();const wsBase=base?base.replace(/^http/,'ws'):`${location.protocol==='https:'?'wss':'ws'}://${location.host}`;return `${wsBase}/ws/${code}?token=${localStorage.getItem('token')}`};
