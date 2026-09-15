export function isAdminRole(role: string | undefined): role is 'admin' | 'super_admin' {
  return role === 'admin' || role === 'super_admin'
}
