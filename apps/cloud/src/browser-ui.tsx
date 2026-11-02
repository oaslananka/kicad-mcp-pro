import {renderPage,Landing,SignIn,Account,Notice} from "./ui-shell.js";
export function renderLanding(identityEnabled:boolean){
  return renderPage({title:"KiCad MCP Cloud",kind:"home",navEnabled:identityEnabled,
    eyebrow:"Cloud console",summary:"Manage AI account access today. Device pairing and local KiCad control are not enabled yet.",
    children:<Landing identityEnabled={identityEnabled}/>});
}
export function renderSignIn(query:string,providers:ReadonlyArray<"google"|"github">=["google","github"]){
  return renderPage({title:"Sign in",kind:"sign-in",eyebrow:"Account access",
    summary:"Use an account to manage AI connections and permissions.",
    children:<SignIn query={query} providers={providers}/>});
}
export function renderAccount(name:string){
  return renderPage({title:"Workspace overview",kind:"account",eyebrow:"Workspace / Overview",
    summary:"Your account, connected AI apps, and device availability in one place.",children:<Account name={name}/>});
}
export function renderNotice(title:string,message:string){
  return renderPage({title,kind:"notice",eyebrow:"Account access",children:<Notice message={message}/>});
}
