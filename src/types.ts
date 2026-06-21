export type Participant={id:string;name:string;team_name:string;primary:string;secondary:string;player_photos:string[];ready:boolean;connected:boolean};
export type Piece={id:string;owner_id:string;role:string;position:{x:number;y:number};velocity:{x:number;y:number};radius:number};
export type LastMove={piece_id:string;direction:{x:number;y:number};force:number;initial:Record<string,{x:number;y:number}>};
export type Match={pieces:Piece[];ball:Piece;turn_player_id:string;score:Record<string,number>;sequence:number;turns_left:number;turn_deadline:number;winner_id:string|null;last_move:LastMove|null};
export type Room={code:string;host_id:string;status:string;participants:Record<string,Participant>;match:Match|null};
export type Team={name:string;short:string;primary:string;secondary:string;players:string[];playerPhotos:string[]};
