/**
 * Bound the latency and memory used to serialize independent readonly tool
 * journeys against one signed owner Connector. A journey includes discovery
 * and execution; serializing individual RPCs would still race between them.
 *
 * WRITE operations must never enter this queue or be retried automatically.
 */
type Waiter={
  resolve:(acquired:boolean)=>void;
  timer:ReturnType<typeof setTimeout>;
};
type Lane={waiters:Waiter[]};
// Typical signed KiCad live-GUI reads take around seven seconds, so two
// queued reads need more than the old four-second tolerance.
const DEFAULT_WAIT_MS=16_000;
const DEFAULT_MAX_WAITERS=3;

export function createCloudReadLane(
  waitMs=DEFAULT_WAIT_MS,maxWaiters=DEFAULT_MAX_WAITERS
){
  const lanes=new Map<string,Lane>();
  return async function run<T>(
    key:string,operation:()=>Promise<T>,onBusy:()=>T
  ):Promise<T>{
    let lane=lanes.get(key);
    if(lane){
      if(lane.waiters.length>=maxWaiters)return onBusy();
      const waiting=lane;
      const acquired=await new Promise<boolean>(resolve=>{
        const waiter:Waiter={
          resolve,
          timer:setTimeout(()=>{
            const position=waiting.waiters.indexOf(waiter);
            if(position>=0)waiting.waiters.splice(position,1);
            resolve(false);
          },waitMs)
        };
        waiting.waiters.push(waiter);
      });
      // A timed-out waiter is removed and must never execute later.
      if(!acquired)return onBusy();
    }else{
      lane={waiters:[]};
      lanes.set(key,lane);
    }
    try{return await operation();}
    finally{
      const next=lane.waiters.shift();
      if(next){
        clearTimeout(next.timer);
        next.resolve(true);
      }else{
        lanes.delete(key);
      }
    }
  };
}

// The inventory is shared by requests within one HTTP server. Weak scoping
// prevents different servers or tests from sharing a device queue.
const inventoryLanes=new WeakMap<object,ReturnType<typeof createCloudReadLane>>();
export function runSerializedCloudRead<T>(
  inventory:object,ownerSub:string,deviceId:string,
  operation:()=>Promise<T>,onBusy:()=>T
):Promise<T>{
  let queue=inventoryLanes.get(inventory);
  if(!queue){
    queue=createCloudReadLane();
    inventoryLanes.set(inventory,queue);
  }
  return queue(JSON.stringify([ownerSub,deviceId]),operation,onBusy);
}
