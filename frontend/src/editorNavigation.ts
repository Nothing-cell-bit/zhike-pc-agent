type Guard=(proceed:()=>void)=>void;
let active:Guard|null=null;
export function registerEditorNavigation(guard:Guard){active=guard;return()=>{if(active===guard)active=null;};}
export function requestEditorNavigation(proceed:()=>void){if(active)active(proceed);else proceed();}
