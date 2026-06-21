# Manu Fut

MVP multiplayer de futebol de botão com React/TypeScript e servidor autoritativo FastAPI/WebSocket.

## Executar

Requer Node 22+ e Python 3.11+. Docker é opcional.

```powershell
Copy-Item .env.example .env
npm install
python -m pip install -r backend/requirements.txt
npm run dev
```

Abra `http://localhost:5173` em dois navegadores (ou uma janela anônima). Crie uma sala no primeiro, entre com o código no segundo e marque ambos como prontos.

## Testes

```powershell
npm run build
npm run test:api
```

## Arquitetura

- `src/`: interface, lobby, canvas do campo e cliente WebSocket.
- `backend/app/game.py`: regras e simulação física independente do transporte.
- `backend/app/store.py`: contrato `RoomStateStore` e implementação em memória.
- `backend/app/main.py`: REST, autenticação e protocolo WebSocket.
- `supabase/migrations/`: esquema permanente, Storage privado e RLS.

## Protocolo WebSocket

Cliente envia `ready`, `move`, `forfeit`, `rematch` e `ping`. Uma jogada contém `piece_id`, vetor `direction`, `force` entre 0 e 1 e `sequence`. O servidor responde com `state`, `error` ou `pong`; somente `state` determina posições, placar e turno.

## Limitações do MVP

O modo local usa tokens `dev-*`; produção deve validar JWT do Supabase. A simulação física é autoritativa e determinística em Python, sem Redis e para uma única instância. Persistência permanente e upload estão modelados na migration, mas precisam das credenciais Supabase para ativação. Antes de produção: persistir snapshots no Supabase, adicionar rate limiting distribuído, validar JWT/JWKS, usar URLs assinadas e executar jobs de expiração/abandono.
