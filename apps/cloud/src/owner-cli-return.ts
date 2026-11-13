/** A same-origin, short-lived sign-in continuation for one CLI request.
 * It is a browser navigation hint, never an approval or an auth token. */
const REQUEST=/^[A-Za-z0-9_-]{43}$/;

export function validCliReturnId(value:string):boolean{
  return REQUEST.test(value);
}
function cookieName(origin:string):string{
  return origin.startsWith("https://")?"__Host-kicad-cli-return":"kicad-cli-return";
}
export function cliReturnCookie(origin:string,requestId:string,seconds:0|600):string{
  if(seconds!==0&&!validCliReturnId(requestId))
    throw Error("Invalid CLI continuation");
  return cookieName(origin)+"="+(seconds?requestId:"")+
    "; Path=/; HttpOnly; SameSite=Strict; Max-Age="+seconds+
    (origin.startsWith("https://")?"; Secure":"");
}
export function readCliReturnCookie(request:Request,origin:string):string|null{
  const name=cookieName(origin)+"=";
  const value=(request.headers.get("cookie")??"").split(";").map(s=>s.trim())
    .find(s=>s.startsWith(name))?.slice(name.length);
  return value&&validCliReturnId(value)?value:null;
}
