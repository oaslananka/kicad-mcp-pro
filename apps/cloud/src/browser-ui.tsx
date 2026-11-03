import {renderPage,Landing,SignIn,Account,Notice} from "./ui-shell.js";
export function renderLanding(identityEnabled:boolean){
  return renderPage({title:"KiCad MCP Cloud",kind:"home",navEnabled:identityEnabled,
    eyebrow:"Cloud console",summary:"Manage AI account access today. Device pairing and local KiCad control are not enabled yet.",
    children:<Landing identityEnabled={identityEnabled}/>});
}
export function renderSignIn(query:string,providers:ReadonlyArray<"google"|"github">=["google","github"],pairing=false){
  return renderPage({title:"Sign in",kind:"sign-in",eyebrow:"Account access",
    summary:"Use an account to manage AI connections and permissions.",
    children:<SignIn query={query} providers={providers} pairing={pairing}/>});
}
export function renderAccount(name:string,
  providers:ReadonlyArray<"google"|"github">=["google","github"],
  linked:ReadonlyArray<"google"|"github">=[]){
  return renderPage({title:"Workspace overview",kind:"account",eyebrow:"Workspace / Overview",
    summary:"Your account, connected AI apps, and device availability in one place.",
    children:<Account name={name} providers={providers} linked={linked}/>});
}
export function renderNotice(title:string,message:string){
  return renderPage({title,kind:"notice",eyebrow:"Account access",children:<Notice message={message}/>});
}
