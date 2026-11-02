import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
export type ConsentView=
  | {kind:"notice";message:string}
  | {kind:"approve";clientName:string;scopes:string[];claims?:string;query:string;csrf:string};
const scopeDetails:Record<string,[string,string]>={
  openid:["Identify your account","The app can confirm which account approved access."],
  profile:["Basic account profile","The app can view basic profile information."],
  offline_access:["Stay connected","The app can request refreshed access without a new sign-in each time."],
  "projects:read":["Read approved projects","The app can list only projects you grant access to separately."]
};
export function renderConsentPage(view:ConsentView):string {
  if(view.kind==="notice")return renderPage({title:"Authorization unavailable",kind:"notice",
    eyebrow:"Connection request",children:<section className="card detail-card"><h2>This request could not be verified</h2>
      <p>{view.message}</p><a href="/" className="mini-link">Back to overview →</a></section>});
  return renderPage({title:"Review app access",kind:"consent",eyebrow:"Connection request",
    summary:"Check the app and permissions before deciding. No access is granted until you approve.",
    children:<section className="card detail-card">
      <div className="card-kicker"><Icon name="shield" size={15}/> APPLICATION REQUESTING ACCESS</div>
      <h2>{view.clientName}</h2>
      <p className="field-help">This app is requesting permission to:</p>
      <ul className="scope-list">{Array.from(new Set(view.scopes)).map(scope=><li key={scope}>
        <strong>{scopeDetails[scope]?.[0]??"Additional permission"}</strong>
        <p>{scopeDetails[scope]?.[1]??"Review this requested permission with the app provider."}</p>
        <code>{scope}</code>
      </li>)}</ul>
      {view.claims?<p className="field-help">Additional claims requested: {view.claims}</p>:null}
      <div className="security-note"><Icon name="lock" size={17}/> Approving account access does not automatically grant access to your KiCad projects. Project grants are separate.</div>
      <form action="/consent" method="post">
        <input type="hidden" name="oauth_query" value={view.query}/><input type="hidden" name="csrf" value={view.csrf}/>
        <div className="form-actions">
          <button className="button reject" name="decision" value="deny" type="submit">Deny</button>
          <button className="button primary" name="decision" value="approve" type="submit">Approve access →</button>
        </div>
      </form>
    </section>});
}
