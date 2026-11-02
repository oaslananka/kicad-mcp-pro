/**
 * Request numbering for a future bounded, authenticated read-only session.
 *
 * Pure state only: DOES NOT authenticate devices, grant owner consent, open
 * sockets, or authorize a project. A caller must perform those checks for
 * EACH request before reserving a sequence. Existing one-shot stays intact.
 */
export class ConnectorReadSequence{
  private next=1;
  private pending:number|null=null;
  private closed=false;

  constructor(private readonly maxReads=16){
    if(!Number.isSafeInteger(maxReads)||maxReads<1||maxReads>65_535)
      throw new RangeError("Invalid read limit");
  }

  /** Serialize one request at a time; no unbounded session growth. */
  reserve():number|null{
    if(this.closed||this.pending!==null||this.next>this.maxReads)return null;
    this.pending=this.next++;
    return this.pending;
  }

  /** Any unsolicited, out-of-order or repeated response poisons the session. */
  complete(sequence:number):boolean{
    if(this.closed||this.pending!==sequence||!Number.isSafeInteger(sequence)){
      this.close();
      return false;
    }
    this.pending=null;
    return true;
  }

  /** Closing/disconnect makes any late result permanently unavailable. */
  close():void{
    this.closed=true;
    this.pending=null;
  }
}
