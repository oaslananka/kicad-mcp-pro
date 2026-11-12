import assert from "node:assert/strict";
import {test} from "node:test";
import {renderPage} from "../src/ui-shell.js";
import {renderSettings} from "../src/browser-ui.js";
import {uiCss} from "../src/ui-styles.js";

test("mobile navigation stays compact while every workspace section is directly reachable",()=>{
  const html=renderPage({title:"Devices",kind:"devices",children:null});
  for(const href of ["/account","/devices","/devices#registered-projects",
                     "/connections","/usage","/settings"]){
    assert.ok(html.includes('href="'+href+'"'),"Missing "+href);
  }
  assert.match(uiCss,/\.workspace-app \.workspace-sidebar\{display:grid;grid-template-columns:minmax\(0,1fr\) auto/);
  assert.match(uiCss,/\.workspace-app \.workspace-sidebar \.sidebar-links\{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(uiCss,/\.workspace-app \.workspace-sidebar \.sidebar-footer-links\{display:none\}/);
  assert.match(uiCss,/\.workspace-app \.workspace-sidebar \.sidebar-links a\{min-height:44px/);
  assert.doesNotMatch(uiCss,/\.device-home-app/);
});

test("account security and help links remain accessible with a compact mobile profile",()=>{
  const html=renderPage({title:"Devices",kind:"devices",children:null,userEmail:"someone@example.invalid"});
  assert.match(html,/href="\/settings" class="sidebar-profile"/);
  assert.match(html,/aria-label="Account and security settings"/);
  const settings=renderSettings("someone@example.invalid");
  assert.match(settings,/href="https:\/\/oaslananka.github.io\/kicad-mcp-pro\/"/);
  assert.match(settings,/href="https:\/\/oaslananka.github.io\/kicad-mcp-pro\/privacy\/"/);
  assert.match(settings,/href="https:\/\/github.com\/oaslananka\/kicad-mcp-pro"/);
});
