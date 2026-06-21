import type {Room,Team} from './types';
const API=import.meta.env.VITE_API_URL||'http://localhost:8000';
export const auth=()=>({Authorization:`Bearer ${localStorage.getItem('token')}`,'Content-Type':'application/json'});
const body=(name:string,team:Team)=>({player_name:name,team_name:team.name,primary:team.primary,secondary:team.secondary});
async function request(path:string,options:RequestInit={}){const r=await fetch(`${API}${path}`,{...options,headers:{...auth(),...options.headers}});if(!r.ok)throw new Error((await r.json()).detail||'Não foi possível continuar');return r.json()}
export const createRoom=(name:string,team:Team):Promise<Room>=>request('/api/rooms',{method:'POST',body:JSON.stringify(body(name,team))});
export const joinRoom=(code:string,name:string,team:Team):Promise<Room>=>request(`/api/rooms/${code}/join`,{method:'POST',body:JSON.stringify(body(name,team))});
export const wsUrl=(code:string)=>`${API.replace('http','ws')}/ws/${code}?token=${localStorage.getItem('token')}`;

