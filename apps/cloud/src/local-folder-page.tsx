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

import type {LocalFolderListing} from "./connector-ws.js";

export type RemoteFolderChoice={
  id:string;name:string;project:boolean;openCsrf:string;selectCsrf?:string;
};
export function renderRemoteFolderPage(
  deviceId:string,listing:LocalFolderListing,
  choices:ReadonlyArray<RemoteFolderChoice>,
  currentSelectCsrf?:string,parentCsrf?:string
):string{
  return renderPage({
    title:"Choose project folder",kind:"devices",
    summary:"Browse folders on your connected computer. Your files stay on that computer.",
    actions:<a className="button secondary" href="/devices">Back to devices</a>,
    children:<div className="page-stack device-folder-workspace">
      <section className="card folder-browser" aria-label="Remote device folder browser">
        <div className="folder-browser-label">
          <Icon name="projects" size={18}/> Connected computer
        </div>
        <h2>{listing.name}</h2>
        <p className="field-help">
          Only folder names are displayed. Select a folder containing a KiCad project.
          No design files are uploaded.
        </p>
        {listing.parentId&&parentCsrf?<form action="/devices/projects/folders" method="post">
          <input type="hidden" name="device_id" value={deviceId}/>
          <input type="hidden" name="folder_id" value={listing.parentId}/>
          <input type="hidden" name="csrf" value={parentCsrf}/>
          <button type="submit" className="button secondary">Back one folder</button>
        </form>:null}
        {currentSelectCsrf&&listing.project?<form className="folder-select-form"
          action="/devices/projects/select" method="post">
          <input type="hidden" name="device_id" value={deviceId}/>
          <input type="hidden" name="folder_id" value={listing.folderId}/>
          <input type="hidden" name="csrf" value={currentSelectCsrf}/>
          <label>Project name
            <input name="alias" required={true} maxLength={64}
              defaultValue={safeAlias(listing.name)} autoComplete="off"/>
          </label>
          <button type="submit" className="button primary">Add this project</button>
        </form>:null}
        {choices.length?<ul className="remote-folder-list">
          {choices.map(folder=><li key={folder.id} className="remote-folder-item">
            <div className="device-project-title"><Icon name="projects" size={18}/>
              <strong>{folder.name}</strong>
              {folder.project?<small>KiCad project</small>:null}
            </div>
            <form action="/devices/projects/folders" method="post">
              <input type="hidden" name="device_id" value={deviceId}/>
              <input type="hidden" name="folder_id" value={folder.id}/>
              <input type="hidden" name="csrf" value={folder.openCsrf}/>
              <button className="button secondary" type="submit">Open folder</button>
            </form>
            {folder.project&&folder.selectCsrf?<form className="folder-select-form"
              action="/devices/projects/select" method="post">
              <input type="hidden" name="device_id" value={deviceId}/>
              <input type="hidden" name="folder_id" value={folder.id}/>
              <input type="hidden" name="csrf" value={folder.selectCsrf}/>
              <label>Project name
                <input name="alias" required={true} maxLength={64}
                  defaultValue={safeAlias(folder.name)} autoComplete="off"/>
              </label>
              <button className="button primary" type="submit">Add project</button>
            </form>:null}
          </li>)}
        </ul>:<p className="field-help">No subfolders here. Go back to choose another folder.</p>}
        {listing.more?<p className="field-help">
          Showing the first 35 folders. Narrow your selection on the computer if needed.
        </p>:null}
      </section>
    </div>
  });
}
