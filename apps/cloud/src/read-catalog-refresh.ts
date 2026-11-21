/**
 * A signed Connector can rotate its session immediately between two queued
 * READ journeys. Discovery is safe to repeat; an executed native tool is not
 * repeated here. The bridge performs fresh signed authorization every attempt.
 */
const READ_CATALOG_RETRY_DELAYS_MS=[450,1_100,2_600] as const;
const MAX_READ_CATALOG_RETRY_ELAPSED_MS=6_000;

export async function retryReadOnlyCatalog<T>(
  fetchCatalog:()=>Promise<T|null>,
  delaysMs:readonly number[]=READ_CATALOG_RETRY_DELAYS_MS,
  maxElapsedMs=MAX_READ_CATALOG_RETRY_ELAPSED_MS
):Promise<T|null>{
  const start=performance.now();
  for(let attempt=0;attempt<=delaysMs.length;attempt++){
    try{
      const current=await fetchCatalog();
      if(current!==null&&current!==undefined)return current;
    }catch{/* A refreshing signed session may temporarily reject discovery. */}
    if(attempt===delaysMs.length)break;
    const delay=delaysMs[attempt]!;
    if(!Number.isFinite(delay)||delay<0||
      performance.now()-start+delay>maxElapsedMs)break;
    await new Promise<void>(resolve=>setTimeout(resolve,delay));
  }
  return null;
}
