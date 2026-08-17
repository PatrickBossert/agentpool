// ui/src/utils/userSort.ts
//
// The sort keys the listings of logins share - the admin user list, and the members tables on
// the org panel and the org detail page.
//
// Stated once rather than per page. CLAUDE.md records what copied conditions do here: the
// register_scripts_sync / scripts_awaiting_regeneration pair diverged and is still divergent.
// A column header naming a key that no comparator answers sorts silently by nothing, which is
// exactly the kind of quiet wrong answer that would never raise anything.
import { personValue } from '../components/PersonCell'
import type { AdminUser, OrgMember } from '../types'

export function userSortKey(user: AdminUser, key: string): string | null {
  switch (key) {
    case 'name':
      return personValue(user.person, 'name')
    case 'entity':
      return personValue(user.person, 'entity')
    case 'username':
      return user.username || null
    case 'email':
      return user.email || null
    case 'role':
      return user.role || null
    case 'created':
      return user.created_at || null
    default:
      return null
  }
}

/** As above, for the org member rows - whose `role` column is the *organisation* role. There
 * is no name here: an organisation is not a project, so there is no lens to read one
 * through. */
export function memberSortKey(member: OrgMember, key: string): string | null {
  switch (key) {
    case 'username':
      return member.username || null
    case 'email':
      return member.email || null
    case 'org_role':
      return member.org_role || null
    default:
      return null
  }
}
