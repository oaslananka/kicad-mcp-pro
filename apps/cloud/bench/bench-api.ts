/** Thin registration API so existing benchmark cases use one small runtime. */
import {Bench} from "tinybench";

type BenchmarkCase = Readonly<{name:string;run:()=>unknown}>;
const cases:BenchmarkCase[]=[];
const groups:string[]=[];

export function describe(name:string, register:()=>void):void {
  groups.push(name);
  try{register();}
  finally{groups.pop();}
}

export function bench(name:string, run:()=>unknown):void {
  cases.push({name:[...groups,name].join(" / "),run});
}

export async function runBenchmarks():Promise<void>{
  if(cases.length===0)throw new Error("No benchmarks registered");
  const suite=new Bench({name:"KiCad Cloud",time:100,iterations:20});
  for(const item of cases)suite.add(item.name,item.run);
  await suite.run();
  console.table(suite.table());
  for(const task of suite.tasks){
    if(task.result && "error" in task.result)throw task.result.error;
  }
}
