import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import {test} from "node:test";

const launcher=resolve(import.meta.dirname,"../assets/connect-windows.cmd");

test("downloadable Windows launcher installs no daemon and runs only the published CLI",()=>{
  const script=readFileSync(launcher,"utf8");
  assert.match(script,/^@echo off/);
  assert.match(script,/call winget install --id astral-sh\.uv --exact --source winget/);
  assert.match(script,/\bcall uvx --from kicad-mcp-pro kicad-mcp-pro cloud connect/);
  assert.doesNotMatch(script,/curl|powershell -ExecutionPolicy|iex|schtasks|\bsc\.exe|--enable-native-write/i);
});

test("downloaded launcher resumes after an existing uvx shim exits",{skip:process.platform!=="win32"},()=>{
  const folder=mkdtempSync(join(tmpdir(),"kicad-cloud-launcher-"));
  try{
    const log=join(folder,"captured.txt");
    writeFileSync(join(folder,"uvx.cmd"),`@echo off\r\necho %* > "${log}"\r\nexit /b 0\r\n`);
    // Only our fake uvx is invoked: no real download, login, project or Cloud mutation.
    const executed=spawnSync(launcher,[],{
      shell:true,input:"\r\n",cwd:folder,encoding:"utf8",timeout:10_000,
      env:{...process.env,PATH:`${folder};${process.env.PATH??""}`}
    });
    assert.equal(executed.error,undefined);
    assert.equal(executed.status,0,executed.stderr||executed.stdout);
    assert.match(executed.stdout,/Cloud session ended/);
    assert.equal(readFileSync(log,"utf8").trim(),"--from kicad-mcp-pro kicad-mcp-pro cloud connect");
  }finally{rmSync(folder,{recursive:true,force:true});}
});


test("launcher can bootstrap uvx from a simulated WinGet install",{skip:process.platform!=="win32"},()=>{
  const folder=mkdtempSync(join(tmpdir(),"kicad-cloud-install-"));
  try{
    const fakeLocal=join(folder,"local");
    const links=join(fakeLocal,"Microsoft","WinGet","Links");
    mkdirSync(links,{recursive:true});
    const cliLog=join(folder,"cli-args.txt");
    const fakeExe=join(folder,"fake-uvx.cmd");
    writeFileSync(fakeExe,"@echo off\r\necho %* > \"%KICAD_SIM_LOG%\"\r\nexit /b 0\r\n");
    writeFileSync(join(folder,"winget.cmd"),
      "@echo off\r\ncopy /Y \"%~dp0fake-uvx.cmd\" \"%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\uvx.cmd\" >nul\r\nexit /b 0\r\n");
    const win=process.env.SystemRoot??"C:\\Windows";
    const executed=spawnSync(launcher,[],{
      shell:true,input:"\r\n",encoding:"utf8",timeout:10_000,
      env:{...process.env,PATH:`${folder};${win}\\System32;${win}`,
        LOCALAPPDATA:fakeLocal,USERPROFILE:join(folder,"home"),KICAD_SIM_LOG:cliLog}
    });
    assert.equal(executed.error,undefined);
    assert.equal(executed.status,0,executed.stderr||executed.stdout);
    assert.match(executed.stdout,/Installing Astral uv/);
    assert.match(executed.stdout,/Cloud session ended/);
    assert.equal(readFileSync(cliLog,"utf8").trim(),"--from kicad-mcp-pro kicad-mcp-pro cloud connect");
  }finally{rmSync(folder,{recursive:true,force:true});}
});

test("launcher reports the missing package manager without changing the system",{skip:process.platform!=="win32"},()=>{
  const folder=mkdtempSync(join(tmpdir(),"kicad-cloud-deny-"));
  try{
    const win=process.env.SystemRoot??"C:\\Windows";
    const executed=spawnSync(launcher,[],{
      shell:true,input:"\r\n",encoding:"utf8",timeout:10_000,
      env:{...process.env,PATH:`${win}\\System32;${win}`,LOCALAPPDATA:folder,USERPROFILE:folder}
    });
    assert.equal(executed.status,2,executed.stderr||executed.stdout);
    assert.match(executed.stdout,/WinGet is unavailable/);
    assert.doesNotMatch(executed.stdout,/Starting the signed foreground/);
  }finally{rmSync(folder,{recursive:true,force:true});}
});
