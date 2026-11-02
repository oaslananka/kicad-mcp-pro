import type {ReactNode} from "react";

export type IconName="logo"|"overview"|"connections"|"devices"|"shield"|"arrow"|"check"|"lock"|"spark"|"activity"|"cloud"|"cpu"|"key"|"github"|"warning";
export function Icon({name,size=20,className=""}:{name:IconName;size?:number;className?:string}){
  const shapes:Record<IconName,ReactNode>={
    logo:<><path d="M5 5h5l4 4h5"/><path d="M5 19h5l4-4h5"/><path d="M5 5v14"/><circle cx="19" cy="9" r="1.5"/><circle cx="19" cy="15" r="1.5"/><circle cx="5" cy="5" r="1.5"/><circle cx="5" cy="19" r="1.5"/></>,
    overview:<><rect x="3" y="3" width="8" height="8" rx="1.6"/><rect x="13" y="3" width="8" height="5" rx="1.6"/><rect x="13" y="10" width="8" height="11" rx="1.6"/><rect x="3" y="13" width="8" height="8" rx="1.6"/></>,
    connections:<><rect x="2.5" y="7.5" width="7" height="9" rx="2"/><rect x="14.5" y="7.5" width="7" height="9" rx="2"/><path d="M9.5 12h5M12 9.5v5"/></>,
    devices:<><rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M9 7h6M10 17h4"/></>,
    shield:<><path d="m12 2 8 4v5c0 5-3.5 8.6-8 11-4.5-2.4-8-6-8-11V6z"/><path d="m9 12 2 2 4-4"/></>,
    arrow:<><path d="M4 12h15m-6-6 6 6-6 6"/></>,
    check:<><path d="m5 12 4 4L19 6"/></>,
    lock:<><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    spark:<><path d="m12 2 1.9 7.2L21 11l-7.1 1.9L12 20l-1.9-7.1L3 11l7.1-1.8z"/></>,
    activity:<><path d="M3 12h4l3-7 4 14 3-7h4"/></>,
    cloud:<><path d="M6 18h12a4 4 0 0 0 .7-7.9A7 7 0 0 0 5.5 9a4.5 4.5 0 0 0 .5 9z"/></>,
    cpu:<><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/><rect x="10" y="10" width="4" height="4" rx=".5"/></>,
    key:<><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9m-3 3 3 3m-6 0 3 3"/></>,
    github:<><path d="M9 20c-4.2 1.4-4.2-2.3-6-2.5m12 5v-3.2a3 3 0 0 0-.9-2.4c3-.3 6.3-1.5 6.3-7a5.4 5.4 0 0 0-1.5-3.7 5 5 0 0 0-.1-3.6s-1.4-.5-3.8 1.4a13 13 0 0 0-7 0C5.6 2.1 4.2 2.6 4.2 2.6a5 5 0 0 0-.1 3.6A5.4 5.4 0 0 0 2.6 10c0 5.5 3.2 6.7 6.2 7a3 3 0 0 0-.9 2.4V23"/></>,
    warning:<><path d="m12 3 10 18H2z"/><path d="M12 9v5m0 3h.01"/></>
  };
  return <svg aria-hidden="true" className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={name==="logo"?1.7:1.65} strokeLinecap="round" strokeLinejoin="round">{shapes[name]}</svg>;
}
