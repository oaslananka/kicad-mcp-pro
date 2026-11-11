import {randomBytes} from "node:crypto";
import type {Config} from "./config.js";
import type {BrowserIdentity} from "./browser.js";

/**
 * A single-user UI development sandbox; never a Cloud account, OAuth provider,
 * device identity or bearer-token issuer. Fail closed unless the entire
 * runtime and database are local and explicitly set to development.
 */
export function createLocalDevIdentity(
  config:Config,env:NodeJS.ProcessEnv=process.env
):BrowserIdentity {
  let db:URL;
  try{db=new URL(config.databaseUrl);}
  catch{throw Error("Local sandbox database URL invalid");}
  if(env.AUTH_MODE!=="local_dev" || env.LOCAL_DEV_SANDBOX!=="acknowledged" ||
    env.NODE_ENV!=="development" ||
    config.host!=="127.0.0.1" ||
    !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{1,4}$/.test(config.publicOrigin) ||
    !["postgres:","postgresql:"].includes(db.protocol) ||
    !["127.0.0.1","localhost"].includes(db.hostname) ||
    !/^\/[a-z0-9_]+_(dev|test)$/.test(db.pathname)){
    throw Error("Local sandbox requires explicit loopback development mode and local test database");
  }
  const secret=randomBytes(48).toString("hex");
  return {
    localDevSandbox:true,
    options:{socialProviders:{}} as NonNullable<BrowserIdentity["options"]>,
    $context:Promise.resolve({secret}) as NonNullable<BrowserIdentity["$context"]>,
    api:{
      getSession:async()=>({
        session:{id:"local-dev-session"},
        user:{id:"local-dev-owner",name:"Local development",email:"sandbox@localhost.invalid"}
      }),
      listUserAccounts:async()=>[],
      getOAuthConsents:async()=>[]
    } as unknown as NonNullable<BrowserIdentity["api"]>,
    handler:async()=>new Response(JSON.stringify({error:"local_sandbox_has_no_oauth"}),{
      status:404,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}
    })
  };
}