import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import type {NativeFolderSelection} from "./connector-ws.js";

export type ProjectChoice = {id:string;name:string;csrf:string};

function safeAlias(label:string):string {
  return label.replace(/[^\p{L}\p{N} ._()-]/gu,"_").slice(0,64).trim() || "KiCad project";
}

/** User chose a directory in Windows. Present its individual KiCad projects,
 * never any absolute Windows paths. No project is registered before Save. */
export function renderLocalFolderPage(
  deviceId:string,selection:NativeFolderSelection,choices:ReadonlyArray<ProjectChoice>
):string{
  if(selection.status!=="selected"||!selection.name||!choices.length)
    throw new Error("Native folder selection is incomplete");
  const single=choices.length===1;
  const folderName=selection.name;
  return renderPage({
    title:"Add project",kind:"devices",
    summary:single?"Confirm the project found in your selected folder.":
      "This folder contains multiple KiCad projects. Choose which one to add.",
    actions:<a className="button secondary" href="/devices">Cancel</a>,
    children:<div className="page-stack device-folder-workspace">
      <section className="card folder-browser" aria-label="Selected KiCad project folder">
        <div className="folder-browser-label">
          <Icon name="check" size={18}/> Folder selected on your computer
        </div>
        <p className="field-help">
          Folder: <strong>{selection.name}</strong>. Your computer found
          {single?" one KiCad project.":" "+choices.length+" KiCad projects."}
          The absolute path stays on your computer.
        </p>
        {choices.map(choice=><form className="folder-select-form"
          action="/devices/projects/select" method="post" key={choice.id}>
          <div className="folder-select-header">
            <Icon name="projects" size={19}/>
            <div>
              <strong>{choice.name+".kicad_pro"}</strong>
              <small>{single?"Ready to add":"Choose this project"}</small>
            </div>
          </div>
          <input type="hidden" name="device_id" value={deviceId}/>
          <input type="hidden" name="folder_id" value={choice.id}/>
          <input type="hidden" name="csrf" value={choice.csrf}/>
          <label>Project name
            <input name="alias" required={true} maxLength={64} autoComplete="off"
              defaultValue={safeAlias(single?folderName:choice.name)}/>
          </label>
          <div className="action-row">
            <button className="button primary" type="submit">Add this project</button>
          </div>
        </form>)}
        <p className="field-help">
          Each project is registered separately. You can rename it later under
          the device's Projects menu. Adding a project grants no AI permissions.
        </p>
      </section>
    </div>
  });
}
