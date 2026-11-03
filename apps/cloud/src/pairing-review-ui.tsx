import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
export function renderPairingReviewPage(csrf:string,notice?:string):string {
  return renderPage({title:"Connect your device",kind:"devices",eyebrow:"DEVICE PAIRING",
    summary:"Start from KiCad on your computer. The pairing details are filled in automatically.",
    children:<section className="card detail-card">
      <div className="card-kicker"><Icon name="shield" size={15}/> SECURE DEVICE APPROVAL</div>
      {notice?<output className="output-notice">{notice}</output>:null}
      <p id="pairing-start">To approve this device, start Connect to Cloud from your KiCad app on this computer.</p>
      <p id="pairing-invalid" role="alert" hidden={true}>This pairing link is invalid or incomplete. Start again from KiCad.</p>
      <div id="pairing-ready" hidden={true}>
        <p><strong>Approve this connection?</strong> Only continue if you started pairing on your own device.</p>
        <p>Verify this code matches KiCad on your computer: <strong id="pairing-code" className="pairing-code"/></p>
      </div>
      <form action="/devices/pairing/review" method="post">
        <details id="pairing-manual">
          <summary>Advanced: enter pairing details manually</summary>
          <label>Pairing challenge ID
            <input id="pairing-id-input" name="challenge_id" required={true} maxLength={36} autoComplete="off"/>
          </label>
          <label>12-character device code
            <input id="pairing-code-input" name="user_code" required={true} minLength={12} maxLength={20} autoComplete="off"/>
          </label>
        </details>
        <input type="hidden" name="csrf" value={csrf}/>
        <div className="action-row" id="pairing-actions">
          <button className="button primary" name="decision" value="approve" type="submit">Approve device</button>
          <button className="button danger" name="decision" value="deny" type="submit">Deny</button>
        </div>
      </form>
      <div className="security-note"><Icon name="lock" size={17}/> Approval alone cannot access projects.
        The device must prove possession of its own private key, and it remains disabled until separately enabled.
        Never approve a request you did not start.</div>
      <a className="mini-link" href="/devices">← Your devices</a>
      <script defer={true} src="/assets/pairing-review.js"></script>
    </section>});
}
