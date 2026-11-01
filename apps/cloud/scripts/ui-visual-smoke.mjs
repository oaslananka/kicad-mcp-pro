import assert from "node:assert/strict";
import {createServer} from "node:http";
import {chromium} from "playwright";
import {renderLanding,renderAccount,renderSignIn} from "../dist/browser-ui.js";
import {renderConnectionsPage} from "../dist/connections-ui.js";
import {renderDevicesPage} from "../dist/devices-ui.js";
import {renderConsentPage} from "../dist/consent-ui.js";
import {uiCss} from "../dist/ui-styles.js";

// Visual/interaction QA for generated HTML without creating any account,
// sharing real user data, or granting OAuth. Browser runs locally only.
const pages=new Map(Object.entries({
  home:renderLanding(true),
  account:renderAccount("Demo Engineer"),
  connections:renderConnectionsPage([{id:"local-demo",name:"ChatGPT",clientId:"test-client",
    scopes:["openid","offline_access","projects:read"],csrf:"test-csrf"}]),
  devices:renderDevicesPage([],undefined,false),
  consent:renderConsentPage({kind:"approve",clientName:"ChatGPT",
    scopes:["openid","offline_access","projects:read"],query:"test",csrf:"test-csrf"}),
  signIn:renderSignIn("",["github"])
}));
// Serve static React-rendered fixture pages over loopback HTTP, as in production.
// Avoid injecting or constructing HTML inside the browser runtime.
const server=createServer((req,res)=>{
  const path=new URL(req.url??"/","http://127.0.0.1").pathname;
  if(path==="/assets/ui.css"){
    res.writeHead(200,{"Content-Type":"text/css; charset=utf-8"});
    res.end(uiCss);return;
  }
  const kind=path.slice(1);
  if(!pages.has(kind)){
    res.writeHead(404);res.end();return;
  }
  res.writeHead(200,{"Content-Type":"text/html; charset=utf-8"});
  res.end(pages.get(kind));
});
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
try{
  for(const [width,height] of [[1440,900],[768,960],[390,844],[375,812],[320,720]]){
    const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
    for(const kind of pages.keys()){
      const response=await page.goto(`${base}/${kind}`,{waitUntil:"load"});
      assert.equal(response?.status(),200);
      const metrics=await page.evaluate(()=>({
        fullWidth:document.documentElement.scrollWidth,
        viewport:window.innerWidth,
        title:document.querySelector("h1")?.textContent?.trim(),
        main:document.querySelectorAll("main").length,
        horizontalOverflow:document.documentElement.scrollWidth-window.innerWidth
      }));
      assert.equal(metrics.main,1,`${kind} must have one main landmark`);
      assert.ok(metrics.title?.length,`${kind} must have a page title`);
      assert.ok(metrics.horizontalOverflow<=1,`${kind} overflows at ${width}: ${metrics.horizontalOverflow}px`);
      if(kind==="account"||kind==="connections"||kind==="devices"){
        assert.equal(await page.locator('nav[aria-label="Workspace"] a').count(),3);
        assert.equal(await page.locator('nav[aria-label="Workspace"] a[aria-current="page"]').count(),1);
        const menu=await page.locator('nav[aria-label="Workspace"]').evaluate(el=>({scroll:el.scrollWidth,visible:el.clientWidth}));
        assert.ok(menu.scroll<=menu.visible+1,`${kind} workspace menu clipped at ${width}px`);
      }
      if(kind==="devices"){
        assert.equal(await page.locator('a[href="/devices/pairing"]').count(),0);
        assert.equal(await page.locator('form[action="/devices/revoke"]').count(),0);
      }
      if(kind==="consent"){
        assert.equal(await page.locator('button[value="approve"]').count(),1);
        assert.equal(await page.locator('button[value="deny"]').count(),1);
      }
      if(kind==="signIn")assert.equal(await page.locator('form[action="/auth/start/github"]').count(),1);
      if(process.env.CAPTURE_UI==="1" && ['account','connections','devices','consent','home'].includes(kind)){
        const file=`/tmp/kicad-cloud-${kind}-${width}.jpg`;
        await page.screenshot({path:file,type:"jpeg",quality:80,fullPage:true});
      }
      console.log(`PASS ${kind} ${width}px: ${metrics.title}`);
    }
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
}
