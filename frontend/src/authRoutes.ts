export const isEmployee=(role?:string)=>role==='staff'||role==='admin';
export const loginDestination=(role?:string)=>role==='admin'?'admin-website':isEmployee(role)?'dashboard':'customer';
export function entryView(path:string,role?:string):string{
 if(!path.startsWith('/staff')&&!path.startsWith('/admin'))return 'customer';
 if(!isEmployee(role))return 'staff-login';
 return role==='admin'?(path.startsWith('/admin/accounts')?'admin-accounts':path.startsWith('/admin/conversations')?'admin-allocation':'admin-website'):'dashboard';
}
export function navigationForRole(role:string|undefined,view:string):string{
 if(role==='admin'&&!['customer','staff-login','admin-website','admin-accounts','admin-allocation'].includes(view))return 'admin-website';
 if(role!=='admin'&&view.startsWith('admin-'))return loginDestination(role);
 return view;
}
export const viewPath=(view:string)=>view==='customer'?'/':view==='staff-login'?'/staff/login':view==='admin-website'?'/admin':view==='admin-accounts'?'/admin/accounts':view==='admin-allocation'?'/admin/conversations':'/staff';
